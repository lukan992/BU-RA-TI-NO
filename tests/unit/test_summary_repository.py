from __future__ import annotations

from dataclasses import dataclass

import pytest

from buratino.models.errors import DataContractError
from buratino.repository.summaries import PostgresSummaryRepository


class FakeCursor:
    def __init__(self, responder) -> None:
        self._responder = responder
        self._query = ""
        self._params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, query: str, params) -> None:
        self._query = query
        self._params = params

    def fetchall(self):
        return self._responder(self._query, self._params)

    def fetchone(self):
        rows = self._responder(self._query, self._params)
        return rows[0] if rows else None


@dataclass
class FakeConnection:
    responder: object

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def cursor(self):
        return FakeCursor(self.responder)


@dataclass
class FakeInspector:
    columns: dict[str, list[str]]
    responder: object

    def list_columns(self, table_name: str) -> list[str]:
        return self.columns.get(table_name, [])

    def connection(self):
        return FakeConnection(self.responder)


def test_summary_repository_prefers_ocr_over_summary() -> None:
    repo = PostgresSummaryRepository(dsn="postgresql://dummy")
    repo._inspector = FakeInspector(
        columns=_base_columns(),
        responder=lambda query, params: _responder(
            query,
            params,
            summary_rows=[{"document_id": "doc-1", "summary_text": "summary text"}],
            ocr_rows=[{"document_id": "doc-1", "ocr_text": "ocr text"}],
        ),
    )

    documents = repo.list_event_documents(42)

    assert len(documents) == 1
    assert documents[0].evidence_source == "ocr"
    assert documents[0].evidence_text == "ocr text"
    assert documents[0].ocr_text == "ocr text"
    assert documents[0].summary_text == "summary text"
    assert documents[0].ocr_parts == ("ocr text",)


def test_summary_repository_uses_summary_when_ocr_missing() -> None:
    repo = PostgresSummaryRepository(dsn="postgresql://dummy")
    repo._inspector = FakeInspector(
        columns=_base_columns(),
        responder=lambda query, params: _responder(
            query,
            params,
            summary_rows=[{"document_id": "doc-1", "summary_text": "summary only"}],
            ocr_rows=[],
        ),
    )

    documents = repo.list_event_documents(42)

    assert len(documents) == 1
    assert documents[0].evidence_source == "summary"
    assert documents[0].evidence_text == "summary only"
    assert documents[0].ocr_text is None
    assert documents[0].summary_text == "summary only"


def test_summary_repository_merges_ocr_pages_when_ocr_present() -> None:
    repo = PostgresSummaryRepository(dsn="postgresql://dummy")
    repo._inspector = FakeInspector(
        columns=_base_columns(),
        responder=lambda query, params: _responder(
            query,
            params,
            summary_rows=[],
            ocr_rows=[
                {"document_id": "doc-1", "ocr_text": "page 1"},
                {"document_id": "doc-1", "ocr_text": "page 2"},
            ],
        ),
    )

    documents = repo.list_event_documents(42)

    assert len(documents) == 1
    assert documents[0].evidence_source == "ocr"
    assert documents[0].evidence_text == "page 1\n\npage 2"
    assert documents[0].ocr_text == "page 1\n\npage 2"
    assert documents[0].ocr_parts == ("page 1", "page 2")


def test_summary_repository_raises_when_no_usable_evidence_exists() -> None:
    repo = PostgresSummaryRepository(dsn="postgresql://dummy")
    repo._inspector = FakeInspector(
        columns=_base_columns(),
        responder=lambda query, params: _responder(
            query,
            params,
            summary_rows=[],
            ocr_rows=[],
            document_count=1,
        ),
    )

    with pytest.raises(DataContractError, match="neither usable OCR text nor summary_text"):
        repo.list_event_documents(42)


def test_summary_repository_file_evidence_includes_documents_without_text() -> None:
    repo = PostgresSummaryRepository(dsn="postgresql://dummy")
    repo._inspector = FakeInspector(
        columns=_base_columns(),
        responder=lambda query, params: _responder(
            query,
            params,
            summary_rows=[],
            ocr_rows=[],
            document_count=1,
        ),
    )

    documents = repo.list_file_evidence(42)

    assert len(documents) == 1
    assert documents[0].file_name == "report.pdf"
    assert documents[0].evidence_source == "none"
    assert documents[0].evidence_text is None


def test_summary_repository_loads_document_date_texts() -> None:
    repo = PostgresSummaryRepository(dsn="postgresql://dummy")
    repo._inspector = FakeInspector(
        columns=_base_columns(),
        responder=lambda query, params: _responder(
            query,
            params,
            summary_rows=[],
            ocr_rows=[],
            date_rows=[{"document_id": "doc-1", "final_text": "Дата документа: 25.12.2025"}],
        ),
    )

    assert repo.get_document_date_texts(["doc-1"]) == {"doc-1": "Дата документа: 25.12.2025"}


def _base_columns() -> dict[str, list[str]]:
    return {
        "documents": ["id", "event_id", "file_name"],
        "document_summary_results": ["document_id", "summary_text"],
        "ocr_results": ["document_id", "full_text", "page_number", "created_at"],
        "date_extraction_results": ["document_id", "final_text"],
        "xlsx_events": ["event_id", "result_value_id"],
    }


def _responder(
    query: str,
    params,
    *,
    summary_rows: list[dict],
    ocr_rows: list[dict],
    date_rows: list[dict] | None = None,
    document_count: int = 0,
):
    if "FROM \"public\".\"xlsx_events\"" in query:
        return []
    if "FROM \"public\".\"documents\" AS d" in query and "SELECT\n                d." in query:
        return [{"document_id": "doc-1", "file_name": "report.pdf"}]
    if "FROM \"public\".\"document_summary_results\" AS s" in query:
        return summary_rows
    if "FROM \"public\".\"ocr_results\" AS o" in query:
        return ocr_rows
    if "FROM \"public\".\"date_extraction_results\" AS d" in query:
        return date_rows or []
    if "count(*) AS document_count" in query:
        return [{"document_count": document_count}]
    if "GROUP BY" in query:
        return []
    return []
