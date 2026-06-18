"""Document summary PostgreSQL repository."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from buratino.models.domain import DocumentSummary, FileEvidence
from buratino.models.errors import DataContractError, NotFoundError
from buratino.repository._postgres import PostgresIntrospector, first_matching_column, quote_ident

DOCUMENTS_TABLE = "documents"
SUMMARY_RESULTS_TABLE = "document_summary_results"
OCR_RESULTS_TABLE = "ocr_results"
DATE_EXTRACTION_RESULTS_TABLE = "date_extraction_results"
XLSX_EVENTS_TABLE = "xlsx_events"

DOCUMENT_ID_CANDIDATES = ("document_id", "id", "report_id", "ИД отчета")
EVENT_ID_CANDIDATES = ("event_id", "ИД мероприятия", "идмероприятия")
FILE_NAME_CANDIDATES = ("file_name", "filename", "source_file_name", "source_filename", "report_name")
SUMMARY_TEXT_CANDIDATES = ("summary_text", "summary", "summarytext")
OCR_TEXT_CANDIDATES = ("full_text", "ocr_text", "text", "content", "raw_text")
DATE_FINAL_TEXT_CANDIDATES = ("final_text", "date_final_text")
PAGE_NUMBER_CANDIDATES = ("page", "page_number", "source_page_number", "page_num")
CREATED_AT_CANDIDATES = ("created_at", "extracted_at", "updated_at")
RESULT_VALUE_ID_CANDIDATES = ("result_value_id", "ИД значения результата", "идзначениярезультата")


class SummaryRepository(Protocol):
    def list_event_documents(self, event_id: int) -> list[DocumentSummary]:
        """Load event documents with active evidence and available fallback texts."""

    def list_file_evidence(self, event_id: int) -> list[FileEvidence]:
        """Load all linked documents for relevance analysis."""

    def get_document_date_texts(self, document_ids: list[str]) -> dict[str, str | None]:
        """Load date extraction final_text by document id."""


@dataclass
class PostgresSummaryRepository:
    """PostgreSQL adapter for OCR/summary evidence."""

    dsn: str
    schema: str = "public"

    def __post_init__(self) -> None:
        self._inspector = PostgresIntrospector(self.dsn, self.schema)

    def list_event_documents(self, event_id: int) -> list[DocumentSummary]:
        documents = self.list_file_evidence(event_id)
        usable_documents = [
            DocumentSummary(
                document_id=document.document_id,
                file_name=document.file_name,
                evidence_text=document.evidence_text,
                evidence_source=document.evidence_source,
                source_table=document.source_table,
                ocr_text=document.ocr_text,
                summary_text=document.summary_text,
                ocr_parts=document.ocr_parts,
            )
            for document in documents
            if document.evidence_source != "none" and document.evidence_text
        ]

        if not usable_documents:
            linkage_ids = self._resolve_linkage_ids(
                event_id=event_id,
                xlsx_event_columns=self._inspector.list_columns(XLSX_EVENTS_TABLE),
            )
            document_count, statuses = self._inspect_documents_without_summaries(linkage_ids)
            if document_count:
                rendered_statuses = ", ".join(
                    f"{status or 'unknown'}={count}" for status, count in statuses
                )
                raise DataContractError(
                    "Documents were found but neither usable OCR text nor summary_text is available for "
                    f"event_id={event_id}; document_count={document_count}; "
                    f"summary_statuses=[{rendered_statuses}]"
                )
            raise DataContractError(f"No usable evidence found for event_id={event_id}")

        return usable_documents

    def list_file_evidence(self, event_id: int) -> list[FileEvidence]:
        documents_columns = self._inspector.list_columns(DOCUMENTS_TABLE)
        summary_columns = self._inspector.list_columns(SUMMARY_RESULTS_TABLE)
        ocr_columns = self._inspector.list_columns(OCR_RESULTS_TABLE)
        xlsx_event_columns = self._inspector.list_columns(XLSX_EVENTS_TABLE)

        if not documents_columns:
            raise DataContractError(
                f"Required table is missing or inaccessible: {self.schema}.{DOCUMENTS_TABLE}"
            )
        if not summary_columns:
            raise DataContractError(
                f"Required table is missing or inaccessible: {self.schema}.{SUMMARY_RESULTS_TABLE}"
            )
        if not ocr_columns:
            raise DataContractError(
                f"Required table is missing or inaccessible: {self.schema}.{OCR_RESULTS_TABLE}"
            )
        if not xlsx_event_columns:
            raise DataContractError(
                f"Required table is missing or inaccessible: {self.schema}.{XLSX_EVENTS_TABLE}"
            )

        document_id_column = first_matching_column(documents_columns, DOCUMENT_ID_CANDIDATES)
        event_id_column = first_matching_column(documents_columns, EVENT_ID_CANDIDATES)
        file_name_column = first_matching_column(documents_columns, FILE_NAME_CANDIDATES)
        summary_document_id_column = first_matching_column(summary_columns, DOCUMENT_ID_CANDIDATES)
        summary_text_column = first_matching_column(summary_columns, SUMMARY_TEXT_CANDIDATES)
        ocr_document_id_column = first_matching_column(ocr_columns, DOCUMENT_ID_CANDIDATES)
        ocr_text_column = first_matching_column(ocr_columns, OCR_TEXT_CANDIDATES)
        ocr_page_column = first_matching_column(ocr_columns, PAGE_NUMBER_CANDIDATES)
        ocr_created_at_column = first_matching_column(ocr_columns, CREATED_AT_CANDIDATES)

        if (
            document_id_column is None
            or event_id_column is None
            or file_name_column is None
            or summary_document_id_column is None
            or summary_text_column is None
            or ocr_document_id_column is None
            or ocr_text_column is None
        ):
            raise DataContractError(
                "Documents, document_summary_results, and ocr_results tables do not expose required columns."
            )
        linkage_ids = self._resolve_linkage_ids(
            event_id=event_id,
            xlsx_event_columns=xlsx_event_columns,
        )
        document_rows = self._load_documents(
            linkage_ids=linkage_ids,
            document_id_column=document_id_column,
            event_id_column=event_id_column,
            file_name_column=file_name_column,
        )
        if not document_rows:
            raise NotFoundError(f"No documents found for event_id={event_id}")

        document_ids = [row["document_id"] for row in document_rows if row["document_id"] is not None]
        summaries_by_document = self._load_summary_map(
            document_ids=document_ids,
            summary_document_id_column=summary_document_id_column,
            summary_text_column=summary_text_column,
        )
        ocr_by_document = self._load_ocr_map(
            document_ids=document_ids,
            ocr_document_id_column=ocr_document_id_column,
            ocr_text_column=ocr_text_column,
            ocr_page_column=ocr_page_column,
            ocr_created_at_column=ocr_created_at_column,
        )

        documents: list[FileEvidence] = []
        for row in document_rows:
            document_id = _strip_or_none(row["document_id"])
            file_name = str(row["file_name"]).strip()
            summary_text = summaries_by_document.get(document_id) if document_id is not None else None
            ocr_evidence = ocr_by_document.get(document_id) if document_id is not None else None
            ocr_text = ocr_evidence.joined_text if ocr_evidence is not None else None
            ocr_parts = ocr_evidence.parts if ocr_evidence is not None else ()
            if ocr_text:
                documents.append(
                    FileEvidence(
                        document_id=document_id,
                        file_name=file_name,
                        evidence_text=ocr_text,
                        evidence_source="ocr",
                        source_table=f"{self.schema}.{DOCUMENTS_TABLE}+{OCR_RESULTS_TABLE}",
                        ocr_text=ocr_text,
                        summary_text=summary_text,
                        ocr_parts=ocr_parts,
                    )
                )
                continue

            if summary_text:
                documents.append(
                    FileEvidence(
                        document_id=document_id,
                        file_name=file_name,
                        evidence_text=summary_text,
                        evidence_source="summary",
                        source_table=f"{self.schema}.{DOCUMENTS_TABLE}+{SUMMARY_RESULTS_TABLE}",
                        ocr_text=None,
                        summary_text=summary_text,
                        ocr_parts=(),
                    )
                )
                continue

            documents.append(
                FileEvidence(
                    document_id=document_id,
                    file_name=file_name,
                    evidence_text=None,
                    evidence_source="none",
                    source_table=f"{self.schema}.{DOCUMENTS_TABLE}",
                    ocr_text=None,
                    summary_text=summary_text,
                    ocr_parts=(),
                )
            )

        return documents

    def get_document_date_texts(self, document_ids: list[str]) -> dict[str, str | None]:
        if not document_ids:
            return {}

        date_columns = self._inspector.list_columns(DATE_EXTRACTION_RESULTS_TABLE)
        if not date_columns:
            return {document_id: None for document_id in document_ids}

        date_document_id_column = first_matching_column(date_columns, DOCUMENT_ID_CANDIDATES)
        final_text_column = first_matching_column(date_columns, DATE_FINAL_TEXT_CANDIDATES)
        if date_document_id_column is None or final_text_column is None:
            raise DataContractError(
                f"Table {self.schema}.{DATE_EXTRACTION_RESULTS_TABLE} does not expose required columns."
            )

        query = f"""
            SELECT
                d.{quote_ident(date_document_id_column)} AS document_id,
                d.{quote_ident(final_text_column)} AS final_text
            FROM {quote_ident(self.schema)}.{quote_ident(DATE_EXTRACTION_RESULTS_TABLE)} AS d
            WHERE d.{quote_ident(date_document_id_column)} = ANY(%s)
        """
        result = {document_id: None for document_id in document_ids}
        with self._inspector.connection() as conn, conn.cursor() as cursor:
            cursor.execute(query, (document_ids,))
            for row in cursor.fetchall():
                document_id = _strip_or_none(row["document_id"])
                if document_id in result and result[document_id] is None:
                    result[document_id] = _strip_or_none(row["final_text"])
        return result

    def _resolve_linkage_ids(self, *, event_id: int, xlsx_event_columns: list[str]) -> list[str]:
        event_id_column = first_matching_column(xlsx_event_columns, EVENT_ID_CANDIDATES)
        result_value_id_column = first_matching_column(xlsx_event_columns, RESULT_VALUE_ID_CANDIDATES)
        if event_id_column is None:
            return [str(event_id)]

        linkage_ids = [str(event_id)]
        if result_value_id_column is None:
            return linkage_ids

        query = f"""
            SELECT {quote_ident(result_value_id_column)} AS result_value_id
            FROM {quote_ident(self.schema)}.{quote_ident(XLSX_EVENTS_TABLE)}
            WHERE {quote_ident(event_id_column)} = %s
              AND {quote_ident(result_value_id_column)} IS NOT NULL
        """
        with self._inspector.connection() as conn, conn.cursor() as cursor:
            cursor.execute(query, (event_id,))
            for row in cursor.fetchall():
                candidate = str(row["result_value_id"]).strip()
                if candidate and candidate not in linkage_ids:
                    linkage_ids.append(candidate)
        return linkage_ids

    def _inspect_documents_without_summaries(
        self,
        linkage_ids: list[str],
    ) -> tuple[int, list[tuple[str | None, int]]]:
        documents_columns = self._inspector.list_columns(DOCUMENTS_TABLE)
        document_event_id_column = first_matching_column(documents_columns, EVENT_ID_CANDIDATES)
        summary_status_column = first_matching_column(documents_columns, ("summary_status",))
        if document_event_id_column is None:
            return 0, []

        count_query = f"""
            SELECT count(*) AS document_count
            FROM {quote_ident(self.schema)}.{quote_ident(DOCUMENTS_TABLE)}
            WHERE {quote_ident(document_event_id_column)} = ANY(%s)
        """
        if summary_status_column is None:
            with self._inspector.connection() as conn, conn.cursor() as cursor:
                cursor.execute(count_query, (linkage_ids,))
                row = cursor.fetchone()
            return int(row["document_count"]), []

        status_query = f"""
            SELECT {quote_ident(summary_status_column)} AS summary_status, count(*) AS item_count
            FROM {quote_ident(self.schema)}.{quote_ident(DOCUMENTS_TABLE)}
            WHERE {quote_ident(document_event_id_column)} = ANY(%s)
            GROUP BY {quote_ident(summary_status_column)}
            ORDER BY {quote_ident(summary_status_column)}
        """
        with self._inspector.connection() as conn, conn.cursor() as cursor:
            cursor.execute(count_query, (linkage_ids,))
            count_row = cursor.fetchone()
            cursor.execute(status_query, (linkage_ids,))
            status_rows = cursor.fetchall()
        return int(count_row["document_count"]), [
            (row["summary_status"], int(row["item_count"])) for row in status_rows
        ]

    def _load_documents(
        self,
        *,
        linkage_ids: list[str],
        document_id_column: str,
        event_id_column: str,
        file_name_column: str,
    ) -> list[dict]:
        query = f"""
            SELECT
                d.{quote_ident(document_id_column)} AS document_id,
                d.{quote_ident(file_name_column)} AS file_name
            FROM {quote_ident(self.schema)}.{quote_ident(DOCUMENTS_TABLE)} AS d
            WHERE d.{quote_ident(event_id_column)} = ANY(%s)
            ORDER BY d.{quote_ident(file_name_column)}
        """
        with self._inspector.connection() as conn, conn.cursor() as cursor:
            cursor.execute(query, (linkage_ids,))
            return cursor.fetchall()

    def _load_summary_map(
        self,
        *,
        document_ids: list[object],
        summary_document_id_column: str,
        summary_text_column: str,
    ) -> dict[str | None, OcrEvidence]:
        if not document_ids:
            return {}

        query = f"""
            SELECT
                s.{quote_ident(summary_document_id_column)} AS document_id,
                s.{quote_ident(summary_text_column)} AS summary_text
            FROM {quote_ident(self.schema)}.{quote_ident(SUMMARY_RESULTS_TABLE)} AS s
            WHERE s.{quote_ident(summary_document_id_column)} = ANY(%s)
        """
        summary_map: dict[str | None, str] = {}
        with self._inspector.connection() as conn, conn.cursor() as cursor:
            cursor.execute(query, (document_ids,))
            for row in cursor.fetchall():
                document_id = _strip_or_none(row["document_id"])
                summary_text = _strip_or_none(row["summary_text"])
                if document_id not in summary_map and summary_text:
                    summary_map[document_id] = summary_text
        return summary_map

    def _load_ocr_map(
        self,
        *,
        document_ids: list[object],
        ocr_document_id_column: str,
        ocr_text_column: str,
        ocr_page_column: str | None,
        ocr_created_at_column: str | None,
    ) -> dict[str | None, str]:
        if not document_ids:
            return {}

        order_parts = [f"o.{quote_ident(ocr_document_id_column)}"]
        if ocr_page_column is not None:
            order_parts.append(f"o.{quote_ident(ocr_page_column)}")
        if ocr_created_at_column is not None:
            order_parts.append(f"o.{quote_ident(ocr_created_at_column)}")

        query = f"""
            SELECT
                o.{quote_ident(ocr_document_id_column)} AS document_id,
                o.{quote_ident(ocr_text_column)} AS ocr_text
            FROM {quote_ident(self.schema)}.{quote_ident(OCR_RESULTS_TABLE)} AS o
            WHERE o.{quote_ident(ocr_document_id_column)} = ANY(%s)
            ORDER BY {", ".join(order_parts)}
        """
        grouped: dict[str | None, list[str]] = {}
        with self._inspector.connection() as conn, conn.cursor() as cursor:
            cursor.execute(query, (document_ids,))
            for row in cursor.fetchall():
                document_id = _strip_or_none(row["document_id"])
                ocr_text = _strip_or_none(row["ocr_text"])
                if not ocr_text:
                    continue
                grouped.setdefault(document_id, []).append(ocr_text)
        return {
            document_id: OcrEvidence(parts=tuple(parts), joined_text="\n\n".join(parts))
            for document_id, parts in grouped.items()
            if parts
        }


@dataclass(frozen=True)
class OcrEvidence:
    parts: tuple[str, ...]
    joined_text: str


def _strip_or_none(value: object) -> str | None:
    if value is None:
        return None
    rendered = str(value).strip()
    return rendered or None
