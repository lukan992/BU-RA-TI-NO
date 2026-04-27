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
        return [DocumentSummary(document_id="doc-1", file_name="report.pdf", evidence_text="summary", evidence_source="summary")]


class SequencedLlmClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses

    def generate_json(self, *, model: str, prompt: str) -> str:
        return self._responses.pop(0)


def test_audit_flips_event_status_when_reasoning_confirms_but_status_is_negative(tmp_path: Path) -> None:
    app = _build_app(
        tmp_path,
        [
            _event_result("не подтверждено", "Есть прямое подтверждение выполнения."),
            _phr_result("не подтверждено", "Нет нужного показателя."),
            _audit_result(False, "подтверждено", "не подтверждено", "Audit logic flip applied."),
        ],
    )

    artifacts = app.verify(
        event_id=42,
        output_dir=tmp_path / "output",
        primary_model="primary",
        audit_model="audit",
        export_xlsx=False,
    )

    assert artifacts.report.event_fact_status == "подтверждено"
    assert artifacts.report.phr_fact_status == "не подтверждено"
    assert artifacts.report.logic_is_valid is False


def test_audit_leaves_statuses_unchanged_when_reasoning_is_not_confirming(tmp_path: Path) -> None:
    app = _build_app(
        tmp_path,
        [
            _event_result("не подтверждено", "Не найдено прямое подтверждение."),
            _phr_result("не подтверждено", "Нет нужного показателя."),
            _audit_result(True, "не подтверждено", "не подтверждено", "Audit logic valid."),
        ],
    )

    artifacts = app.verify(
        event_id=42,
        output_dir=tmp_path / "output",
        primary_model="primary",
        audit_model="audit",
        export_xlsx=False,
    )

    assert artifacts.report.event_fact_status == "не подтверждено"
    assert artifacts.report.phr_fact_status == "не подтверждено"
    assert artifacts.report.logic_is_valid is True


def test_audit_does_not_change_confirmed_status(tmp_path: Path) -> None:
    app = _build_app(
        tmp_path,
        [
            _event_result("подтверждено", "Есть прямое подтверждение выполнения."),
            _phr_result("подтверждено", "Показатель достигнут."),
            _audit_result(True, "подтверждено", "подтверждено", "Audit logic valid."),
        ],
    )

    artifacts = app.verify(
        event_id=42,
        output_dir=tmp_path / "output",
        primary_model="primary",
        audit_model="audit",
        export_xlsx=False,
    )

    assert artifacts.report.event_fact_status == "подтверждено"
    assert artifacts.report.phr_fact_status == "подтверждено"
    assert artifacts.report.logic_is_valid is True


def test_audit_leaves_ambiguous_reasoning_unchanged(tmp_path: Path) -> None:
    app = _build_app(
        tmp_path,
        [
            _event_result("не подтверждено", "Возможно подтверждение, но данных недостаточно."),
            _phr_result("не подтверждено", "Скорее всего показатель достигнут."),
            _audit_result(True, "не подтверждено", "не подтверждено", "Audit logic valid."),
        ],
    )

    artifacts = app.verify(
        event_id=42,
        output_dir=tmp_path / "output",
        primary_model="primary",
        audit_model="audit",
        export_xlsx=False,
    )

    assert artifacts.report.event_fact_status == "не подтверждено"
    assert artifacts.report.phr_fact_status == "не подтверждено"
    assert artifacts.report.logic_is_valid is True


def _build_app(tmp_path: Path, responses: list[str]) -> VerificationApp:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    llm = SequencedLlmClient(responses)
    prompt_loader = PromptLoader(prompts_dir)
    return VerificationApp(
        event_repository=FakeEventRepository(),
        summary_repository=FakeSummaryRepository(),
        target_builder=TargetBuilder(prompt_loader, llm, "primary"),
        event_verifier=EventVerifier(prompt_loader, llm, "primary"),
        phr_verifier=PhrVerifier(prompt_loader, llm, "primary"),
        audit_service=AuditService(prompt_loader, llm, "audit"),
    )


def _event_result(status: str, reasoning: str) -> str:
    confirmed = status == "подтверждено"
    return json.dumps(
        {
            "document_id": "doc-1",
            "file_name": "report.pdf",
            "fact_status": status,
            "reasoning": reasoning,
            "matched_action": "Построить" if confirmed else None,
            "matched_subject": "спортивный объект" if confirmed else None,
            "completion_signal": "введен в эксплуатацию" if confirmed else None,
            "observed_value": 2 if confirmed else None,
            "observed_unit": "ед" if confirmed else None,
            "comparison_result": "meets_target" if confirmed else "insufficient_data",
            "evidence_quote": "введены 2 объекта" if confirmed else None,
        }
    )


def _phr_result(status: str, reasoning: str) -> str:
    confirmed = status == "подтверждено"
    return json.dumps(
        {
            "document_id": "doc-1",
            "file_name": "report.pdf",
            "phr_fact_status": status,
            "reasoning": reasoning,
            "metric_matched": "Количество введенных объектов" if confirmed else None,
            "characteristic_explicitly_matched": confirmed,
            "quantity_refers_to_metric_object": confirmed,
            "observed_value": 2 if confirmed else None,
            "observed_unit": "ед" if confirmed else None,
            "comparison_result": "meets_target" if confirmed else "insufficient_data",
            "evidence_quote": "введены 2 объекта" if confirmed else None,
        }
    )


def _audit_result(logic_is_valid: bool, event_status: str, phr_status: str, reasoning: str) -> str:
    return json.dumps(
        {
            "logic_is_valid": logic_is_valid,
            "detected_errors": [] if logic_is_valid else ["contradiction"],
            "corrected_event_status": event_status,
            "corrected_phr_status": phr_status,
            "corrected_reasoning": reasoning,
        }
    )
