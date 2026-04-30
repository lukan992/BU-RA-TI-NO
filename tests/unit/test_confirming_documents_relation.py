from __future__ import annotations

import json
from pathlib import Path

from buratino.llm.prompt_loader import PromptLoader
from buratino.models.contracts import DocumentFactResult
from buratino.models.domain import DocumentSummary, EventRecord
from buratino.verifier.confirming_documents_relation import (
    ConfirmingDocument,
    ConfirmingDocumentsRelationService,
    aggregate_deadline_status,
    build_document_date_checks,
    compare_document_date,
    extract_document_date,
    select_confirming_documents,
)
from conftest import create_prompt_assets


class RecordingLlmClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.prompts: list[str] = []

    def generate_json(self, *, model: str, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._responses.pop(0)


class FakeSummaryRepository:
    def __init__(self, date_texts: dict[str, str | None]) -> None:
        self.date_texts = date_texts

    def get_document_date_texts(self, document_ids: list[str]) -> dict[str, str | None]:
        return {document_id: self.date_texts.get(document_id) for document_id in document_ids}


def test_selects_only_event_confirming_documents() -> None:
    documents = [
        DocumentSummary("doc-1", "primary.pdf", "summary 1", "summary"),
        DocumentSummary("doc-2", "negative.pdf", "summary 2", "summary"),
        DocumentSummary("doc-3", "not-in-event-results.pdf", "summary 3", "summary"),
    ]
    event_results = [
        DocumentFactResult("doc-1", "primary.pdf", "подтверждено", "ok"),
        DocumentFactResult("doc-2", "negative.pdf", "не подтверждено", "no"),
    ]

    selected = select_confirming_documents(
        documents=documents,
        event_results=event_results,
        event_fact_status="подтверждено",
        event_primary_file="primary.pdf",
        event_supporting_files=["primary.pdf"],
    )

    assert [document.document_id for document in selected] == ["doc-1"]


def test_relation_service_builds_comma_separated_file_ids(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)
    llm = RecordingLlmClient(
        [
            json.dumps(
                {
                    "event_id": 42,
                    "file_ids": "doc-1,doc-2",
                    "reasoning": "Документы описывают тот же объект и действие мероприятия.",
                    "relation_status": "относится",
                },
                ensure_ascii=False,
            )
        ]
    )
    service = ConfirmingDocumentsRelationService(
        prompt_loader=PromptLoader(prompts_dir),
        llm_client=llm,
        primary_model="primary",
        summary_repository=FakeSummaryRepository(
            {
                "doc-1": "Дата документа: 25.12.2025 номер 1",
                "doc-2": "Дата документа: 24.12.2025 номер 2",
            }
        ),
    )

    relation, error = service.build(
        event=EventRecord(42, "Построить объект", "Описание", 2, "ед", "2025-12-31"),
        documents=[
            DocumentSummary("doc-1", "a.pdf", "summary 1", "summary"),
            DocumentSummary("doc-2", "b.pdf", "summary 2", "summary"),
        ],
        event_results=[
            DocumentFactResult("doc-1", "a.pdf", "подтверждено", "ok"),
            DocumentFactResult("doc-2", "b.pdf", "подтверждено", "ok"),
        ],
        event_fact_status="подтверждено",
        event_primary_file="a.pdf",
        event_supporting_files=["a.pdf", "b.pdf"],
    )

    assert error is None
    assert relation.file_ids == "doc-1,doc-2"
    assert relation.relation_status == "относится"
    assert relation.confirming_documents_within_deadline_status == "да"
    assert len(llm.prompts) == 1
    assert "negative.pdf" not in llm.prompts[0]


def test_extract_document_date_from_final_text() -> None:
    assert extract_document_date("foo Дата документа: 25.12.2025 бар").isoformat() == "2025-12-25"


def test_compare_document_date_statuses() -> None:
    document_date = extract_document_date("Дата документа: 25.12.2025")

    assert compare_document_date(document_date=document_date, implementation_deadline="2025-12-31")[0] == "да"
    assert compare_document_date(document_date=document_date, implementation_deadline="2025-12-24")[0] == "нет"
    assert compare_document_date(document_date=None, implementation_deadline="2025-12-31")[0] == "невозможно определить"


def test_build_document_date_checks_and_aggregate_late_status() -> None:
    documents = [
        ConfirmingDocument("doc-1", "a.pdf", "summary", "text", "reason", None),
        ConfirmingDocument("doc-2", "b.pdf", "summary", "text", "reason", None),
    ]

    checks = build_document_date_checks(
        documents=documents,
        implementation_deadline_raw="2025-12-31",
        date_texts={
            "doc-1": "Дата документа: 25.12.2025",
            "doc-2": "Дата документа: 01.01.2026",
        },
    )

    assert checks[0].within_implementation_deadline == "да"
    assert checks[1].within_implementation_deadline == "нет"
    assert aggregate_deadline_status(checks) == "нет"
