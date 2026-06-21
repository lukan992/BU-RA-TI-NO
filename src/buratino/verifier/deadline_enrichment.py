"""Deadline enrichment for already confirmed supporting files."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from buratino.models.contracts import DocumentFactResult
from buratino.models.domain import DocumentSummary, EventRecord
from buratino.repository.summaries import SummaryRepository

DATE_PATTERN = re.compile(r"(\d{2}[.-]\d{2}[.-]\d{4}|\d{4}-\d{2}-\d{2})")


@dataclass(frozen=True)
class DeadlineEnrichmentResult:
    status: str = "not_checked"
    reason: str | None = None
    document_date: str | None = None
    source_file: str | None = None
    source: str | None = None
    raw_text: str | None = None
    implementation_deadline_raw: str | None = None
    implementation_deadline_normalized: str | None = None
    date_checked_files: list[str] = field(default_factory=list)
    date_missing_files: list[str] = field(default_factory=list)
    date_late_files: list[str] = field(default_factory=list)
    date_on_time_files: list[str] = field(default_factory=list)
    supporting_files_date_status: dict[str, str] = field(default_factory=dict)


@dataclass
class DeadlineEnrichmentService:
    summary_repository: SummaryRepository

    def build(
        self,
        *,
        event: EventRecord,
        documents: list[DocumentSummary],
        event_results: list[DocumentFactResult],
        supporting_files: list[str],
    ) -> DeadlineEnrichmentResult:
        deadline_raw = event.implementation_deadline
        deadline_normalized = _normalize_date(deadline_raw)
        if not supporting_files:
            return DeadlineEnrichmentResult(
                status="not_checked",
                reason="Подтверждающие документы отсутствуют, проверка срока не выполнялась.",
                implementation_deadline_raw=deadline_raw,
                implementation_deadline_normalized=deadline_normalized,
            )
        if deadline_normalized is None:
            return DeadlineEnrichmentResult(
                status="deadline_missing",
                reason="Срок реализации в xlsx_events не заполнен или не распознан.",
                implementation_deadline_raw=deadline_raw,
                implementation_deadline_normalized=None,
            )

        confirmed_event_files = {
            result.file_name for result in event_results if result.fact_status == "подтверждено"
        }
        candidate_documents = [
            document
            for document in documents
            if document.file_name in supporting_files and document.file_name in confirmed_event_files
        ]
        if not candidate_documents:
            return DeadlineEnrichmentResult(
                status="not_checked",
                reason="Для срока не найдено event-level подтверждающих OCR документов.",
                implementation_deadline_raw=deadline_raw,
                implementation_deadline_normalized=deadline_normalized,
            )

        date_texts = self.summary_repository.get_document_date_texts(
            [document.document_id for document in candidate_documents if document.document_id]
        )
        supporting_status: dict[str, str] = {}
        checked_files: list[str] = []
        missing_files: list[str] = []
        late_files: list[str] = []
        on_time_files: list[str] = []
        best: DeadlineEnrichmentResult | None = None

        for document in candidate_documents:
            raw_text, source = self._select_date_text(document=document, date_texts=date_texts)
            normalized_date = _extract_single_date(raw_text)
            if normalized_date is None:
                supporting_status[document.file_name] = "document_date_missing"
                missing_files.append(document.file_name)
                if best is None:
                    best = DeadlineEnrichmentResult(
                        status="document_date_missing",
                        reason="Дата документа не найдена в date extraction и OCR.",
                        source_file=document.file_name,
                        source=source,
                        raw_text=raw_text,
                        implementation_deadline_raw=deadline_raw,
                        implementation_deadline_normalized=deadline_normalized,
                    )
                continue

            checked_files.append(document.file_name)
            if normalized_date <= deadline_normalized:
                supporting_status[document.file_name] = "on_time"
                on_time_files.append(document.file_name)
                best = DeadlineEnrichmentResult(
                    status="on_time",
                    reason=(
                        f"Дата документа {normalized_date} не позже срока реализации {deadline_normalized}."
                    ),
                    document_date=normalized_date,
                    source_file=document.file_name,
                    source=source,
                    raw_text=raw_text,
                    implementation_deadline_raw=deadline_raw,
                    implementation_deadline_normalized=deadline_normalized,
                )
                break

            supporting_status[document.file_name] = "late"
            late_files.append(document.file_name)
            if best is None or best.status != "on_time":
                best = DeadlineEnrichmentResult(
                    status="late",
                    reason=(
                        f"Дата документа {normalized_date} позже срока реализации {deadline_normalized}."
                    ),
                    document_date=normalized_date,
                    source_file=document.file_name,
                    source=source,
                    raw_text=raw_text,
                    implementation_deadline_raw=deadline_raw,
                    implementation_deadline_normalized=deadline_normalized,
                )

        result = best or DeadlineEnrichmentResult(
            status="not_checked",
            reason="Проверка срока не дала результата.",
            implementation_deadline_raw=deadline_raw,
            implementation_deadline_normalized=deadline_normalized,
        )
        return DeadlineEnrichmentResult(
            status=result.status,
            reason=result.reason,
            document_date=result.document_date,
            source_file=result.source_file,
            source=result.source,
            raw_text=result.raw_text,
            implementation_deadline_raw=deadline_raw,
            implementation_deadline_normalized=deadline_normalized,
            date_checked_files=checked_files,
            date_missing_files=missing_files,
            date_late_files=late_files,
            date_on_time_files=on_time_files,
            supporting_files_date_status=supporting_status,
        )

    @staticmethod
    def _select_date_text(
        *,
        document: DocumentSummary,
        date_texts: dict[str, str | None],
    ) -> tuple[str | None, str]:
        if document.document_id is not None:
            final_text = date_texts.get(document.document_id)
            if final_text:
                return final_text, "date_extraction_results.final_text"
        if document.ocr_text:
            return document.ocr_text, "ocr"
        return None, "missing"


def _normalize_date(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    return _extract_single_date(raw_value)


def _extract_single_date(text: str | None) -> str | None:
    if text is None:
        return None
    matches = DATE_PATTERN.findall(text)
    normalized = sorted({value for value in (_parse_date(item) for item in matches) if value is not None})
    if len(normalized) != 1:
        return None
    return normalized[0]


def _parse_date(raw_value: str) -> str | None:
    for fmt in ("%d.%m.%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(raw_value, fmt)
        except ValueError:
            continue
        return parsed.date().isoformat()
    return None
