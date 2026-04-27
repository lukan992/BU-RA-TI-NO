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


def test_summary_repository_prefers_summary_over_ocr() -> None:
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
    assert documents[0].evidence_source == "summary"
    assert documents[0].evidence_text == "summary text"


def test_summary_repository_falls_back_to_ocr_when_summary_missing() -> None:
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

    with pytest.raises(DataContractError, match="neither usable summary_text nor OCR text"):
        repo.list_event_documents(42)


def _base_columns() -> dict[str, list[str]]:
    return {
        "documents": ["id", "event_id", "file_name"],
        "document_summary_results": ["document_id", "summary_text"],
        "ocr_results": ["document_id", "full_text", "page_number", "created_at"],
        "xlsx_events": ["event_id", "result_value_id"],
    }


def _responder(
    query: str,
    params,
    *,
    summary_rows: list[dict],
    ocr_rows: list[dict],
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
    if "count(*) AS document_count" in query:
        return [{"document_count": document_count}]
    if "GROUP BY" in query:
        return []
    return []
