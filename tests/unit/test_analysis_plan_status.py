from __future__ import annotations

from dataclasses import dataclass

from buratino.models.contracts import DocumentFactResult, EvidenceItem, ReasoningTrace
from buratino.models.domain import EventRecord, FileEvidence, VerificationTarget
from buratino.models.errors import NotFoundError
from buratino.service.analysis import BuratinoAnalysisService


@dataclass
class FakeEventRepository:
    event: EventRecord

    def get_event(self, event_id: int) -> EventRecord:
        del event_id
        return self.event

    def get_event_phr(self, event_id: int):
        del event_id
        raise NotFoundError("no phr")


@dataclass
class FakeSummaryRepository:
    file_evidence: list[FileEvidence]

    def list_file_evidence(self, event_id: int) -> list[FileEvidence]:
        del event_id
        return self.file_evidence


@dataclass
class FakeTargetBuilder:
    event_target: VerificationTarget

    def build_event_target(self, event):
        del event
        return self.event_target

    def build_phr_target(self, event, phr):  # pragma: no cover - phr is absent in these tests
        del event, phr
        return None


@dataclass
class FakeEventVerifier:
    results: list[DocumentFactResult]

    def verify_documents(self, target, documents, *, model=None):
        del target, model
        return self.results, documents


class FakePhrVerifier:
    def verify_documents(self, target, documents, *, model=None):  # pragma: no cover - phr absent
        del target, model
        return [], documents


def _service(*, event: EventRecord, target: VerificationTarget, event_results: list[DocumentFactResult]):
    file_evidence = [
        FileEvidence(
            document_id="doc-1",
            file_name="report.pdf",
            evidence_text="ocr text",
            evidence_source="ocr",
            ocr_text="ocr text",
        )
    ]
    return BuratinoAnalysisService(
        event_repository=FakeEventRepository(event=event),
        summary_repository=FakeSummaryRepository(file_evidence=file_evidence),
        target_builder=FakeTargetBuilder(event_target=target),
        document_ranking_service=None,
        event_verifier=FakeEventVerifier(results=event_results),
        phr_verifier=FakePhrVerifier(),
        primary_model="primary",
        ranking_model=None,
        audit_model=None,
    )


def _confirmed_result(**overrides) -> DocumentFactResult:
    base = dict(
        document_id="doc-1",
        file_name="report.pdf",
        fact_status="подтверждено",
        reasoning="OCR подтверждает выполнение.",
        evidence_quote="создан объект",
        reasoning_trace=ReasoningTrace(
            evidence_items=[EvidenceItem(quote="создан объект", page=None, source="ocr", why_relevant="факт")],
            short_rationale="подтверждение найдено",
        ),
    )
    base.update(overrides)
    return DocumentFactResult(**base)


def test_planned_value_one_keeps_plan_status_applicable() -> None:
    """planned_value present => plan_status must not be 'Не применимо' (bug regression)."""
    event = EventRecord(9187621740, "Создать объект", "описание", 1.0, "Единица")
    # Simulate the LLM resolving event_type to qualitative for planned_value=1.
    target = VerificationTarget(
        event_id=9187621740,
        event_name="Создать объект",
        event_description="описание",
        event_type="qualitative",
        normalized_action="Создать объект",
        normalized_subject="описание",
        planned_value=1.0,
        planned_unit="Единица",
    )
    service = _service(event=event, target=target, event_results=[_confirmed_result()])

    result = service.analyze_event(9187621740, payload={"result_value_id": 9187621740})

    statuses = result["statuses"]
    assert statuses["plan_status"] != "Не применимо"
    assert statuses["plan_status"] == "Подтверждено"
    assert statuses["event_description_status"] == "Подтверждено"
    assert result["result_value_id"] == 9187621740


def test_quantitative_event_not_confirmed_when_plan_below_target() -> None:
    """event_description_status cannot be confirmed when the quantitative plan is not confirmed."""
    event = EventRecord(555, "Построить объекты", "описание", 5.0, "ед")
    target = VerificationTarget(
        event_id=555,
        event_name="Построить объекты",
        event_description="описание",
        event_type="quantitative",
        normalized_action="Построить объекты",
        normalized_subject="описание",
        planned_value=5.0,
        planned_unit="ед",
    )
    below_target = _confirmed_result(
        comparison_result="below_target",
        observed_value=2,
        observed_unit="ед",
    )
    service = _service(event=event, target=target, event_results=[below_target])

    result = service.analyze_event(555, payload={})

    statuses = result["statuses"]
    assert statuses["plan_status"] == "Не подтверждено"
    assert statuses["plan_status"] != "Не применимо"
    assert statuses["event_description_status"] == "Не подтверждено"
