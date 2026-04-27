from __future__ import annotations

import json
from pathlib import Path

from buratino.app import VerificationApp
from buratino.audit.service import AuditService
from buratino.llm.prompt_loader import PromptLoader
from buratino.models.domain import DocumentSummary, EventRecord, PhrRecord
from buratino.target_builder.service import TargetBuilder
from buratino.verifier.event_verifier import EventVerifier
from buratino.verifier.phr_verifier import PhrVerifier
from conftest import create_prompt_assets


class FakeEventRepository:
    def get_event(self, event_id: int) -> EventRecord:
        return EventRecord(
            event_id=event_id,
            event_name="Построить спортивный объект",
            event_description="Построить объект и ввести его в эксплуатацию",
            planned_value=2,
            planned_unit="ед",
        )

    def get_event_phr(self, event_id: int) -> PhrRecord:
        return PhrRecord(
            event_id=event_id,
            phr_name="Количество введенных объектов",
            phr_value_2025=2,
            phr_unit="ед",
        )


class FakeSummaryRepository:
    def list_event_documents(self, event_id: int) -> list[DocumentSummary]:
        return [
            DocumentSummary(document_id="doc-1", file_name="report-1.pdf", evidence_text="summary 1", evidence_source="summary"),
            DocumentSummary(document_id="doc-2", file_name="report-2.pdf", evidence_text="summary 2", evidence_source="summary"),
        ]


class SequencedLlmClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses

    def generate_json(self, *, model: str, prompt: str) -> str:
        return self._responses.pop(0)


def test_happy_path_generates_json_and_xlsx(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    llm = SequencedLlmClient(
        [
            json.dumps(
                {
                    "document_id": "doc-1",
                    "file_name": "report-1.pdf",
                    "fact_status": "подтверждено",
                    "reasoning": "Есть прямое подтверждение выполнения.",
                    "matched_action": "Построить",
                    "matched_subject": "спортивный объект",
                    "completion_signal": "введен в эксплуатацию",
                    "observed_value": 2,
                    "observed_unit": "ед",
                    "comparison_result": "meets_target",
                    "evidence_quote": "введены 2 объекта",
                }
            ),
            json.dumps(
                {
                    "document_id": "doc-2",
                    "file_name": "report-2.pdf",
                    "fact_status": "не подтверждено",
                    "reasoning": "Документ не содержит прямого факта.",
                    "matched_action": None,
                    "matched_subject": None,
                    "completion_signal": None,
                    "observed_value": None,
                    "observed_unit": None,
                    "comparison_result": "insufficient_data",
                    "evidence_quote": None,
                }
            ),
            json.dumps(
                {
                    "document_id": "doc-1",
                    "file_name": "report-1.pdf",
                    "phr_fact_status": "подтверждено",
                    "reasoning": "Показатель достигнут.",
                    "metric_matched": "Количество введенных объектов",
                    "characteristic_explicitly_matched": True,
                    "quantity_refers_to_metric_object": True,
                    "observed_value": 2,
                    "observed_unit": "ед",
                    "comparison_result": "meets_target",
                    "evidence_quote": "введены 2 объекта",
                }
            ),
            json.dumps(
                {
                    "document_id": "doc-2",
                    "file_name": "report-2.pdf",
                    "phr_fact_status": "не подтверждено",
                    "reasoning": "Нет нужного показателя.",
                    "metric_matched": None,
                    "characteristic_explicitly_matched": False,
                    "quantity_refers_to_metric_object": False,
                    "observed_value": None,
                    "observed_unit": None,
                    "comparison_result": "insufficient_data",
                    "evidence_quote": None,
                }
            ),
            json.dumps(
                {
                    "logic_is_valid": True,
                    "detected_errors": [],
                    "corrected_event_status": "подтверждено",
                    "corrected_phr_status": "подтверждено",
                    "corrected_reasoning": "Логика корректна.",
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
        event_id=42,
        output_dir=tmp_path / "output",
        primary_model="primary",
        audit_model="audit",
        export_xlsx=True,
    )

    assert artifacts.report.event_fact_status == "подтверждено"
    assert artifacts.report.phr_fact_status == "подтверждено"
    assert "summary документа" in artifacts.report.event_reasoning
    assert artifacts.report.event_reasoning.count(".") >= 3
    assert "summary документа" in artifacts.report.phr_reasoning
    assert artifacts.report.phr_reasoning.count(".") >= 3
    assert artifacts.json_path.exists()
    assert artifacts.xlsx_path is not None and artifacts.xlsx_path.exists()
