"""Relation and deadline checks for event-confirming documents."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from itertools import islice

from loguru import logger

from buratino.llm.client import is_context_overflow_error
from buratino.llm.client import LlmClient
from buratino.llm.json_parser import parse_confirming_documents_relation_result
from buratino.llm.prompt_loader import PromptLoader
from buratino.models.contracts import (
    ConfirmingDocumentsRelation,
    DocumentDateCheck,
    DocumentFactResult,
    RelationDateCheck,
    RelationMatrixItem,
)
from buratino.models.domain import DeadlineStatus, DocumentSummary, EventRecord
from buratino.repository.summaries import SummaryRepository
from buratino.verifier.ocr_chunking import OcrChunker

MISSING_CONFIRMING_DOCUMENTS_REASONING = (
    "Мероприятие не подтверждено документами, поэтому подтверждающие документы для проверки отношения отсутствуют."
)
RELATION_ERROR_PREFIX = "Confirming documents relation check failed"
DEFAULT_RELATION_MAX_TEXT_CHARS = 6000
DATE_MARKER_PATTERN = re.compile(
    r"Дата документа:\s*(\d{2}[.-]\d{2}[.-]\d{4}|\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ConfirmingDocument:
    document_id: str | None
    file_name: str
    evidence_source: str
    evidence_text: str
    fact_reasoning: str
    evidence_quote: str | None


@dataclass
class ConfirmingDocumentsRelationService:
    prompt_loader: PromptLoader
    llm_client: LlmClient
    primary_model: str
    summary_repository: SummaryRepository
    max_text_chars: int = DEFAULT_RELATION_MAX_TEXT_CHARS
    batch_size: int = 5
    chunker: OcrChunker = OcrChunker(40000, 1500, 120)

    def build(
        self,
        *,
        event: EventRecord,
        documents: list[DocumentSummary],
        event_results: list[DocumentFactResult],
        event_fact_status: str,
        event_primary_file: str | None,
        event_supporting_files: list[str],
        model: str | None = None,
    ) -> tuple[ConfirmingDocumentsRelation, str | None]:
        confirming_documents = select_confirming_documents(
            documents=documents,
            event_results=event_results,
            event_fact_status=event_fact_status,
            event_primary_file=event_primary_file,
            event_supporting_files=event_supporting_files,
        )
        if not confirming_documents:
            return self._empty_relation(event), None

        date_error = None
        try:
            date_texts = self.summary_repository.get_document_date_texts(
                [document.document_id for document in confirming_documents if document.document_id]
            )
        except Exception as exc:
            date_error = f"Confirming documents date check failed: {exc}"
            logger.error(date_error)
            date_texts = {}

        date_checks = build_document_date_checks(
            documents=confirming_documents,
            implementation_deadline_raw=event.implementation_deadline,
            date_texts=date_texts,
        )
        deadline_status = aggregate_deadline_status(date_checks)
        try:
            relation_results = self._run_relation_with_overflow_recovery(
                event=event,
                documents=confirming_documents,
                model=model or self.primary_model,
            )
            relation_matrix = build_relation_matrix(
                documents=confirming_documents,
                relation_results=relation_results,
                date_checks=date_checks,
                implementation_deadline=event.implementation_deadline,
            )
            return self._build_relation(
                event=event,
                documents=confirming_documents,
                date_checks=date_checks,
                deadline_status=deadline_status,
                relation_matrix=relation_matrix,
            ), date_error
        except Exception as exc:
            error = f"{RELATION_ERROR_PREFIX}: {exc}"
            if date_error is not None:
                error = f"{date_error}; {error}"
            logger.error(error)
            return self._error_relation(
                event=event,
                documents=confirming_documents,
                date_checks=date_checks,
                deadline_status=deadline_status,
                error=error,
            ), error

    def _empty_relation(self, event: EventRecord) -> ConfirmingDocumentsRelation:
        return ConfirmingDocumentsRelation(
            event_id=event.event_id,
            file_ids="",
            file_names="",
            reasoning=MISSING_CONFIRMING_DOCUMENTS_REASONING,
            relation_status="не относится",
            implementation_deadline=normalize_date_string(event.implementation_deadline),
            confirming_documents_within_deadline_status="невозможно определить",
            document_date_checks=[],
            relation_matrix=[],
        )

    def _error_relation(
        self,
        *,
        event: EventRecord,
        documents: list[ConfirmingDocument],
        date_checks: list[DocumentDateCheck],
        deadline_status: DeadlineStatus,
        error: str,
    ) -> ConfirmingDocumentsRelation:
        return ConfirmingDocumentsRelation(
            event_id=event.event_id,
            file_ids=",".join(document.document_id or "" for document in documents),
            file_names=", ".join(document.file_name for document in documents),
            reasoning=error,
            relation_status="не относится",
            implementation_deadline=normalize_date_string(event.implementation_deadline),
            confirming_documents_within_deadline_status=deadline_status,
            document_date_checks=date_checks,
            relation_matrix=[],
        )

    def _build_relation(
        self,
        *,
        event: EventRecord,
        documents: list[ConfirmingDocument],
        date_checks: list[DocumentDateCheck],
        deadline_status: DeadlineStatus,
        relation_matrix: list[RelationMatrixItem],
    ) -> ConfirmingDocumentsRelation:
        relation_status = (
            "относится"
            if any(item.relation_to_event in {"direct", "indirect"} for item in relation_matrix)
            else "не относится"
        )
        reasoning = " ".join(item.relation_reason for item in relation_matrix if item.relation_reason.strip())
        return ConfirmingDocumentsRelation(
            event_id=event.event_id,
            file_ids=",".join(document.document_id or "" for document in documents),
            file_names=", ".join(document.file_name for document in documents),
            reasoning=reasoning or MISSING_CONFIRMING_DOCUMENTS_REASONING,
            relation_status=relation_status,
            implementation_deadline=normalize_date_string(event.implementation_deadline),
            confirming_documents_within_deadline_status=deadline_status,
            document_date_checks=date_checks,
            relation_matrix=relation_matrix,
        )

    def _run_relation_with_overflow_recovery(
        self,
        *,
        event: EventRecord,
        documents: list[ConfirmingDocument],
        model: str,
    ) -> list[dict[str, str | None]]:
        try:
            return self._run_relation_once(
                event=event,
                documents=documents,
                model=model,
            )
        except Exception as exc:
            if not is_context_overflow_error(exc):
                raise
            logger.warning(
                "Confirming documents relation overflow: event_id={} document_count={}; retrying with grouped relation",
                event.event_id,
                len(documents),
            )
            return self._run_relation_grouped(event=event, documents=documents, model=model)

    def _run_relation_once(
        self,
        *,
        event: EventRecord,
        documents: list[ConfirmingDocument],
        model: str,
    ) -> list[dict[str, str | None]]:
        prompt = self.prompt_loader.render(
            "confirming_documents_relation.md",
            {
                "event_id": event.event_id,
                "event_name": event.event_name,
                "event_description": event.event_description,
                "documents": [self._serialize_document(document) for document in documents],
            },
        )
        raw_response = self.llm_client.generate_json(model=model, prompt=prompt)
        return parse_confirming_documents_relation_result(raw_response).documents

    def _run_relation_grouped(
        self,
        *,
        event: EventRecord,
        documents: list[ConfirmingDocument],
        model: str,
    ) -> list[dict[str, str | None]]:
        merged: list[dict[str, str | None]] = []
        for group in _batched(documents, self.batch_size):
            try:
                merged.extend(self._run_relation_once(event=event, documents=group, model=model))
            except Exception as exc:
                if not is_context_overflow_error(exc) or len(group) != 1:
                    raise
                merged.append(self._run_single_document_relation_chunks(event=event, document=group[0], model=model))
        return merged

    def _run_single_document_relation_chunks(
        self,
        *,
        event: EventRecord,
        document: ConfirmingDocument,
        model: str,
    ) -> dict[str, str | None]:
        chunk_build = self.chunker.build_text_chunks(
            DocumentSummary(
                document_id=document.document_id,
                file_name=document.file_name,
                evidence_text=document.evidence_text,
                evidence_source=document.evidence_source,
                summary_text=document.evidence_text if document.evidence_source == "summary" else None,
                ocr_text=document.evidence_text if document.evidence_source == "ocr" else None,
            )
        )
        if chunk_build.exceeded_limit or not chunk_build.chunks:
            raise ValueError(f"Relation chunking failed for file={document.file_name}")
        chunk_results: list[dict[str, str | None]] = []
        for chunk in chunk_build.chunks:
            chunk_document = ConfirmingDocument(
                document_id=document.document_id,
                file_name=document.file_name,
                evidence_source=document.evidence_source,
                evidence_text=self._limit_text(chunk.evidence_text),
                fact_reasoning=document.fact_reasoning,
                evidence_quote=document.evidence_quote,
            )
            chunk_results.extend(
                self._run_relation_once(event=event, documents=[chunk_document], model=model)
            )
        return next(
            (
                item
                for item in chunk_results
                if item["relation_to_event"] in {"direct", "indirect"}
            ),
            chunk_results[0],
        )

    def _limit_text(self, text: str) -> str:
        return text if len(text) <= self.max_text_chars else text[: self.max_text_chars]

    def _serialize_document(self, document: ConfirmingDocument) -> dict[str, object]:
        return {
            "doc_id": document.document_id,
            "file_name": document.file_name,
            "evidence_source": document.evidence_source,
            "evidence_text": self._limit_text(document.evidence_text),
            "fact_reasoning": document.fact_reasoning,
            "evidence_quote": document.evidence_quote,
        }


def select_confirming_documents(
    *,
    documents: list[DocumentSummary],
    event_results: list[DocumentFactResult],
    event_fact_status: str,
    event_primary_file: str | None,
    event_supporting_files: list[str],
) -> list[ConfirmingDocument]:
    if event_fact_status != "подтверждено":
        return []
    document_map = {document.file_name: document for document in documents}
    allowed_files = set(event_supporting_files)
    if event_primary_file:
        allowed_files.add(event_primary_file)
    selected: list[ConfirmingDocument] = []
    seen: set[tuple[str | None, str]] = set()
    for result in event_results:
        if result.fact_status != "подтверждено" or not result.reasoning_trace.evidence_items:
            continue
        if allowed_files and result.file_name not in allowed_files:
            continue
        document = document_map.get(result.file_name)
        if document is None:
            continue
        identity = (document.document_id, document.file_name)
        if identity in seen:
            continue
        seen.add(identity)
        selected.append(
            ConfirmingDocument(
                document_id=document.document_id,
                file_name=document.file_name,
                evidence_source=document.evidence_source,
                evidence_text=document.evidence_text,
                fact_reasoning=result.reasoning,
                evidence_quote=result.evidence_quote,
            )
        )
    return selected


def build_relation_matrix(
    *,
    documents: list[ConfirmingDocument],
    relation_results: list[dict[str, str | None]],
    date_checks: list[DocumentDateCheck],
    implementation_deadline: str | None,
) -> list[RelationMatrixItem]:
    date_checks_by_doc = {item.document_id: item for item in date_checks}
    relation_by_doc = {item["doc_id"]: item for item in relation_results}
    event_period = {"start": None, "end": normalize_date_string(implementation_deadline)}
    matrix: list[RelationMatrixItem] = []
    for document in documents:
        relation = relation_by_doc.get(document.document_id, {})
        relation_to_event = relation.get("relation_to_event") or "unclear"
        relation_reason = relation.get("relation_reason") or "Связь документа с мероприятием не определена."
        date_check_source = date_checks_by_doc.get(document.document_id)
        date_check = _build_relation_date_check(date_check_source, event_period=event_period)
        allowed = (
            relation_to_event in {"direct", "indirect"}
            and date_check.status == "inside_period"
        )
        matrix.append(
            RelationMatrixItem(
                doc_id=document.document_id,
                file_name=document.file_name,
                relation_to_event=relation_to_event,  # type: ignore[arg-type]
                relation_reason=relation_reason,
                date_check=date_check,
                allowed_as_supporting_file=allowed,
            )
        )
    return matrix


def _build_relation_date_check(
    date_check: DocumentDateCheck | None,
    *,
    event_period: dict[str, str | None],
) -> RelationDateCheck:
    if date_check is None:
        return RelationDateCheck(
            status="unclear",
            document_dates=[],
            event_period=event_period,
            short_reason="Дата документа не была проверена.",
        )
    status = {
        "да": "inside_period",
        "нет": "outside_period",
        "невозможно определить": "no_date" if date_check.document_date is None else "unclear",
    }[date_check.within_implementation_deadline]
    document_dates = [date_check.document_date] if date_check.document_date is not None else []
    return RelationDateCheck(
        status=status,
        document_dates=document_dates,
        event_period=event_period,
        short_reason=date_check.date_reasoning,
    )


def _batched(items: list[ConfirmingDocument], batch_size: int) -> list[list[ConfirmingDocument]]:
    iterator = iter(items)
    batches: list[list[ConfirmingDocument]] = []
    while batch := list(islice(iterator, batch_size)):
        batches.append(batch)
    return batches


def build_document_date_checks(
    *,
    documents: list[ConfirmingDocument],
    implementation_deadline_raw: str | None,
    date_texts: dict[str, str | None],
) -> list[DocumentDateCheck]:
    implementation_deadline = parse_date(implementation_deadline_raw)
    checks: list[DocumentDateCheck] = []
    for document in documents:
        final_text = date_texts.get(document.document_id or "")
        document_date = extract_document_date(final_text)
        status, reasoning = compare_document_date(
            document_date=document_date,
            implementation_deadline=implementation_deadline,
        )
        checks.append(
            DocumentDateCheck(
                document_id=document.document_id,
                file_name=document.file_name,
                date_final_text=final_text,
                document_date=document_date.isoformat() if document_date is not None else None,
                implementation_deadline=implementation_deadline.isoformat()
                if implementation_deadline is not None
                else None,
                within_implementation_deadline=status,
                date_reasoning=reasoning,
            )
        )
    return checks


def extract_document_date(final_text: str | None) -> date | None:
    if not final_text:
        return None
    match = DATE_MARKER_PATTERN.search(final_text)
    if match is None:
        return None
    return parse_date(match.group(1))


def normalize_date_string(raw_value: str | None) -> str | None:
    parsed = parse_date(raw_value)
    return parsed.isoformat() if parsed is not None else None


def parse_date(raw_value: str | None) -> date | None:
    if not raw_value:
        return None
    value = str(raw_value).strip()
    patterns = (
        (r"\d{2}\.\d{2}\.\d{4}", "%d.%m.%Y"),
        (r"\d{2}-\d{2}-\d{4}", "%d-%m-%Y"),
        (r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d"),
    )
    for pattern, fmt in patterns:
        match = re.search(pattern, value)
        if match is None:
            continue
        return datetime.strptime(match.group(0), fmt).date()
    return None


def compare_document_date(
    *,
    document_date: date | None,
    implementation_deadline: str | date | None,
) -> tuple[DeadlineStatus, str]:
    deadline = implementation_deadline if isinstance(implementation_deadline, date) else parse_date(implementation_deadline)
    if deadline is None:
        return "невозможно определить", "Срок реализации мероприятия отсутствует или не распознан."
    if document_date is None:
        return "невозможно определить", "Дата документа не найдена или не распознана."
    if document_date <= deadline:
        return "да", f"Дата документа {document_date.isoformat()} не позже срока реализации {deadline.isoformat()}."
    return "нет", f"Дата документа {document_date.isoformat()} позже срока реализации {deadline.isoformat()}."


def aggregate_deadline_status(checks: list[DocumentDateCheck]) -> DeadlineStatus:
    if not checks:
        return "невозможно определить"
    statuses = [check.within_implementation_deadline for check in checks]
    if "нет" in statuses:
        return "нет"
    if all(status == "да" for status in statuses):
        return "да"
    return "невозможно определить"
