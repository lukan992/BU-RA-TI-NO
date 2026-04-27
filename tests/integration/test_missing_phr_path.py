from __future__ import annotations

import json
from pathlib import Path

from buratino.app import VerificationApp
from buratino.audit.service import AuditService
from buratino.llm.prompt_loader import PromptLoader
from buratino.models.domain import DocumentSummary, EventRecord
from buratino.models.errors import NotFoundError
from buratino.target_builder.service import TargetBuilder
from buratino.verifier.event_verifier import EventVerifier
from buratino.verifier.phr_verifier import PhrVerifier
from conftest import create_prompt_assets


class FakeEventRepository:
    def get_event(self, event_id: int) -> EventRecord:
        return EventRecord(
            event_id=event_id,
            event_name="Проверить мероприятие",
            event_description="Факт выполнения",
            planned_value=0,
            planned_unit="шт",
        )

    def get_event_phr(self, event_id: int):
        raise NotFoundError("PHR not found")


class FakeSummaryRepository:
    def list_event_documents(self, event_id: int) -> list[DocumentSummary]:
        return [DocumentSummary(document_id="doc-1", file_name="report.pdf", evidence_text="summary", evidence_source="summary")]


class SequencedLlmClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.prompts: list[str] = []

    def generate_json(self, *, model: str, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._responses.pop(0)


def test_missing_phr_is_reported_as_not_defined(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    llm = SequencedLlmClient(
        [
            json.dumps(
                {
                    "document_id": "doc-1",
                    "file_name": "report.pdf",
                    "fact_status": "подтверждено",
                    "reasoning": "Факт подтвержден.",
                    "matched_action": "Проверить мероприятие",
                    "matched_subject": "Факт выполнения",
                    "completion_signal": "выполнено",
                    "observed_value": None,
                    "observed_unit": None,
                    "comparison_result": "not_applicable",
                    "evidence_quote": "выполнено",
                }
            ),
            json.dumps(
                {
                    "logic_is_valid": True,
                    "detected_errors": [],
                    "corrected_event_status": "подтверждено",
                    "corrected_phr_status": "не указано",
                    "corrected_reasoning": "ПХР не задан, логика event корректна.",
                }
            ),
        ]
    )

    prompt_loader = PromptLoader(prompts_dir)
    app = VerificationApp(
        event_repository=FakeEventRepository(),
        summary_repository=FakeSummaryRepository(),
        target_builder=TargetBuilder(prompt_loader, llm, "primary"),
        event_verifier=EventVerifier(prompt_loader, llm, "primary"),
        phr_verifier=PhrVerifier(prompt_loader, llm, "primary"),
        audit_service=AuditService(prompt_loader, llm, "audit"),
    )

    artifacts = app.verify(
        event_id=1,
        output_dir=tmp_path / "output",
        primary_model="primary",
        audit_model="audit",
        export_xlsx=False,
    )

    assert artifacts.report.event_fact_status == "подтверждено"
    assert artifacts.report.phr_fact_status == "не указано"
    assert "ПХР не задан" in artifacts.report.phr_reasoning
    assert artifacts.report.phr_reasoning.count(".") >= 2
    assert artifacts.report.phr_documents == []
    assert len(llm.prompts) == 2
