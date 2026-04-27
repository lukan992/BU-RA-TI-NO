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
            event_name="Проверить мероприятие",
            event_description="Факт выполнения",
            planned_value=0,
            planned_unit="шт",
        )

    def get_event_phr(self, event_id: int) -> PhrRecord:
        return PhrRecord(
            event_id=event_id,
            phr_name="Количество участников",
            phr_value_2025=10,
            phr_unit="чел",
        )


class FakeSummaryRepository:
    def list_event_documents(self, event_id: int) -> list[DocumentSummary]:
        return [DocumentSummary(document_id="doc-1", file_name="report.pdf", evidence_text="ocr text", evidence_source="ocr")]


class RecordingLlmClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.prompts: list[str] = []

    def generate_json(self, *, model: str, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._responses.pop(0)


def test_ocr_fallback_passes_ocr_evidence_to_prompts(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    llm = RecordingLlmClient(
        [
            json.dumps(
                {
                    "document_id": "doc-1",
                    "file_name": "report.pdf",
                    "fact_status": "не подтверждено",
                    "reasoning": "OCR использован. Явного факта выполнения нет. Обязательные сигналы не найдены. Поэтому статус не подтвержден.",
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
                    "file_name": "report.pdf",
                    "phr_fact_status": "не подтверждено",
                    "reasoning": "OCR использован. Характеристика объекта не подтверждена. Количество не привязано к метрике. Поэтому статус не подтвержден.",
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
                    "corrected_event_status": "не подтверждено",
                    "corrected_phr_status": "не подтверждено",
                    "corrected_reasoning": "Logic is valid.",
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

    assert artifacts.report.event_reasoning.count(".") >= 3
    assert "ocr" in llm.prompts[0]
    assert "\"evidence_source\": \"ocr\"" in llm.prompts[0]
    assert "\"evidence_text\": \"ocr text\"" in llm.prompts[0]
