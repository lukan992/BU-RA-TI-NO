from __future__ import annotations

import json
from pathlib import Path

from buratino.app import VerificationApp
from buratino.audit.service import AuditService
from buratino.llm.prompt_loader import PromptLoader
from buratino.models.domain import DocumentSummary, EventRecord, PhrRecord
from buratino.target_builder.service import TargetBuilder
from buratino.verifier.document_ranking import DocumentRankingService
from buratino.verifier.event_verifier import EventVerifier
from buratino.verifier.phr_verifier import PhrVerifier
from conftest import create_prompt_assets


class FakeEventRepository:
    def get_event(self, event_id: int) -> EventRecord:
        return EventRecord(
            event_id=event_id,
            event_name="Обеспечить проведение мероприятия",
            event_description="Факт должен быть подтвержден напрямую",
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
        return [
            DocumentSummary(
                document_id="doc-1",
                file_name="report.pdf",
                evidence_text="ocr",
                evidence_source="ocr",
                ocr_text="ocr",
                summary_text="summary",
                ocr_parts=("ocr",),
            )
        ]


class SequencedLlmClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses

    def generate_json(self, *, model: str, prompt: str) -> str:
        return self._responses.pop(0)


def _reasoning_trace(confirmed: bool, quote: str | None = None) -> dict[str, object]:
    return {
        "reason_codes": ["mentions_completion_fact"] if confirmed else ["insufficient_evidence"],
        "evidence_items": (
            [
                {
                    "quote": quote or "evidence",
                    "page": None,
                    "source": "ocr",
                    "why_relevant": "Decision-significant evidence.",
                }
            ]
            if confirmed and quote is not None
            else []
        ),
        "missing_requirements": [] if confirmed else ["explicit evidence"],
        "short_rationale": "trace",
        "confidence": "high" if confirmed else "low",
    }


def test_fail_closed_path_stays_not_confirmed(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    llm = SequencedLlmClient(
        [
            json.dumps(
                {
                    "document_id": "doc-1",
                    "file_name": "report.pdf",
                    "fact_status": "не подтверждено",
                    "reasoning": "Summary содержит сведения о поставке 15 единиц БАС производства ООО «Геоскан», но не содержит прямого подтверждения выполнения целевого мероприятия.",
                    "matched_action": None,
                    "matched_subject": None,
                    "completion_signal": None,
                    "observed_value": None,
                    "observed_unit": None,
                    "comparison_result": "insufficient_data",
                    "evidence_quote": "Предметом акта является поставка 15 единиц беспилотных авиационных систем (БАС) производства ООО «Геоскан»",
                    "reasoning_trace": _reasoning_trace(
                        False,
                        "Предметом акта является поставка 15 единиц беспилотных авиационных систем (БАС) производства ООО «Геоскан»",
                    ),
                }
            ),
            json.dumps(
                {
                    "document_id": "doc-1",
                    "file_name": "report.pdf",
                    "phr_fact_status": "не подтверждено",
                    "reasoning": "Нет фактического значения.",
                    "metric_matched": None,
                    "characteristic_explicitly_matched": False,
                    "quantity_refers_to_metric_object": False,
                    "observed_value": None,
                    "observed_unit": None,
                    "comparison_result": "insufficient_data",
                    "evidence_quote": None,
                    "reasoning_trace": _reasoning_trace(False),
                }
            ),
            json.dumps(
                {
                    "audit_result": "pass",
                    "rule_violations": [],
                    "final_event_fact_status": "не подтверждено",
                    "final_phr_fact_status": "не подтверждено",
                    "final_supporting_files": [],
                }
            ),
        ]
    )

    prompt_loader = PromptLoader(prompts_dir)
    app = VerificationApp(
        event_repository=FakeEventRepository(),
        summary_repository=FakeSummaryRepository(),
        target_builder=TargetBuilder(prompt_loader, llm, "primary"),
        document_ranking_service=DocumentRankingService(prompt_loader, llm, "ranking"),
        event_verifier=EventVerifier(prompt_loader, llm, "primary"),
        phr_verifier=PhrVerifier(prompt_loader, llm, "primary"),
        audit_service=AuditService(prompt_loader, llm, "audit"),
    )

    artifacts = app.verify(
        event_id=7,
        output_dir=tmp_path / "output",
        primary_model="primary",
        audit_model="audit",
        export_xlsx=False,
    )

    assert artifacts.report.event_fact_status == "не подтверждено"
    assert artifacts.report.phr_fact_status == "не подтверждено"
    assert "report.pdf" in artifacts.report.event_reasoning
    assert "не подтверждено" in artifacts.report.event_reasoning
    assert artifacts.report.event_reasoning.count(".") >= 3
    assert "Количество участников" in artifacts.report.phr_reasoning
    assert artifacts.report.phr_reasoning.count(".") >= 3
    assert "Doc-level" not in artifacts.report.event_reasoning
    assert "summary документа" not in artifacts.report.event_reasoning
    assert artifacts.report.logic_is_valid == "not_checked"


def test_phr_stays_fail_closed_when_llm_marks_confirmed_but_value_is_below_target(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    llm = SequencedLlmClient(
        [
            json.dumps(
                {
                    "document_id": "doc-1",
                    "file_name": "report.pdf",
                    "fact_status": "не подтверждено",
                    "reasoning": "Есть только план.",
                    "matched_action": None,
                    "matched_subject": None,
                    "completion_signal": None,
                    "observed_value": None,
                    "observed_unit": None,
                    "comparison_result": "insufficient_data",
                    "evidence_quote": None,
                    "reasoning_trace": _reasoning_trace(False),
                }
            ),
            json.dumps(
                {
                    "document_id": "doc-1",
                    "file_name": "report.pdf",
                    "phr_fact_status": "подтверждено",
                    "reasoning": "Число есть, но оно ниже целевого значения.",
                    "metric_matched": "Количество участников",
                    "characteristic_explicitly_matched": True,
                    "quantity_refers_to_metric_object": True,
                    "observed_value": 5,
                    "observed_unit": "чел",
                    "comparison_result": "below_target",
                    "evidence_quote": "участвовали 5 человек",
                    "reasoning_trace": _reasoning_trace(True, "участвовали 5 человек"),
                }
            ),
            json.dumps(
                {
                    "audit_result": "pass",
                    "rule_violations": [],
                    "final_event_fact_status": "не подтверждено",
                    "final_phr_fact_status": "подтверждено",
                    "final_supporting_files": [],
                }
            ),
        ]
    )

    prompt_loader = PromptLoader(prompts_dir)
    app = VerificationApp(
        event_repository=FakeEventRepository(),
        summary_repository=FakeSummaryRepository(),
        target_builder=TargetBuilder(prompt_loader, llm, "primary"),
        document_ranking_service=DocumentRankingService(prompt_loader, llm, "ranking"),
        event_verifier=EventVerifier(prompt_loader, llm, "primary"),
        phr_verifier=PhrVerifier(prompt_loader, llm, "primary"),
        audit_service=AuditService(prompt_loader, llm, "audit"),
    )

    artifacts = app.verify(
        event_id=8,
        output_dir=tmp_path / "output",
        primary_model="primary",
        audit_model="audit",
        export_xlsx=False,
    )

    assert artifacts.report.phr_fact_status == "не подтверждено"
    assert "значение показателя, которое подтверждает выполнение требования в полном объеме" in artifacts.report.phr_reasoning
    assert "не подтверждено" in artifacts.report.phr_reasoning
