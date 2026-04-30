"""Relation and deadline checks for event-confirming documents."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from loguru import logger

from buratino.llm.client import LlmClient
from buratino.llm.json_parser import parse_confirming_documents_relation_result
from buratino.llm.prompt_loader import PromptLoader
from buratino.models.contracts import (
    ConfirmingDocumentsRelation,
    DocumentDateCheck,
    DocumentFactResult,
)
from buratino.models.domain import DeadlineStatus, DocumentSummary, EventRecord
from buratino.repository.summaries import SummaryRepository

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
        logger.info("Confirming documents relation check: count={}", len(confirming_documents))
        logger.info(
            "Confirming documents relation check: document_ids={}",
            ", ".join(document.document_id or "" for document in confirming_documents),
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

        file_ids = ",".join(document.document_id or "" for document in confirming_documents)
        file_names = ", ".join(document.file_name for document in confirming_documents)
        try:
            logger.info("Running confirming documents relation LLM prompt")
            prompt = self.prompt_loader.render(
                "confirming_documents_relation.md",
                {
                    "event_id": event.event_id,
                    "event_name": event.event_name,
                    "event_description": event.event_description,
                    "file_ids": file_ids,
                    "documents": [
                        {
                            "document_id": document.document_id,
                            "file_name": document.file_name,
                            "evidence_source": document.evidence_source,
                            "evidence_text": self._limit_text(document.evidence_text),
                            "fact_reasoning": document.fact_reasoning,
                            "evidence_quote": document.evidence_quote,
                        }
                        for document in confirming_documents
                    ],
                },
            )
            raw_response = self.llm_client.generate_json(model=model or self.primary_model, prompt=prompt)
            llm_result = parse_confirming_documents_relation_result(raw_response)
            relation = ConfirmingDocumentsRelation(
                event_id=event.event_id,
                file_ids=file_ids,
                file_names=file_names,
                reasoning=llm_result.reasoning,
                relation_status=llm_result.relation_status,
                implementation_deadline=normalize_date_string(event.implementation_deadline),
                confirming_documents_within_deadline_status=deadline_status,
                document_date_checks=date_checks,
            )
            logger.info("Confirming documents relation status={}", relation.relation_status)
            return relation, date_error
        except Exception as exc:
            error = f"{RELATION_ERROR_PREFIX}: {exc}"
            if date_error is not None:
                error = f"{date_error}; {error}"
            logger.error(error)
            return (
                ConfirmingDocumentsRelation(
                    event_id=event.event_id,
                    file_ids=file_ids,
                    file_names=file_names,
                    reasoning=error,
                    relation_status="не относится",
                    implementation_deadline=normalize_date_string(event.implementation_deadline),
                    confirming_documents_within_deadline_status=deadline_status,
                    document_date_checks=date_checks,
                ),
                error,
            )

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
        )

    def _limit_text(self, text: str) -> str:
        return text if len(text) <= self.max_text_chars else text[: self.max_text_chars]


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
    selected: list[ConfirmingDocument] = []
    seen: set[tuple[str | None, str]] = set()
    for result in event_results:
        if result.fact_status != "подтверждено":
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
