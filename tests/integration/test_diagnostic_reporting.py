from __future__ import annotations

import json
from pathlib import Path

from buratino.app import VerificationApp
from buratino.audit.service import AuditService
from buratino.llm.prompt_loader import PromptLoader
from buratino.models.domain import DocumentSummary, EventRecord, PhrRecord
from buratino.target_builder.service import TargetBuilder
from buratino.verifier.deadline_enrichment import DeadlineEnrichmentService
from buratino.verifier.document_ranking import DocumentRankingService
from buratino.verifier.event_verifier import EventVerifier
from buratino.verifier.phr_verifier import PhrVerifier
from conftest import create_prompt_assets


class FakeEventRepository:
    def get_event(self, event_id: int) -> EventRecord:
        return EventRecord(
            event_id=event_id,
            event_name="Событие",
            event_description="Описание",
            planned_value=0,
            planned_unit="шт",
            implementation_deadline="2025-12-31",
        )

    def get_event_phr(self, event_id: int) -> PhrRecord:
        return PhrRecord(event_id=event_id, phr_name="ПХР", phr_value_2025=0, phr_unit="шт")


class FakeSummaryRepository:
    def __init__(self, *, date_text: str | None = "Дата документа: 25.12.2025") -> None:
        self._date_text = date_text

    def list_event_documents(self, event_id: int) -> list[DocumentSummary]:
        return [
            DocumentSummary(
                document_id="doc-1",
                file_name="doc.pdf",
                evidence_text="ocr text",
                evidence_source="ocr",
                ocr_text="ocr text",
                summary_text="summary text",
                ocr_parts=("ocr text",),
            )
        ]

    def get_document_date_texts(self, document_ids: list[str]) -> dict[str, str | None]:
        return {document_id: self._date_text for document_id in document_ids}


class SequencedLlmClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses

    def generate_json(self, *, model: str, prompt: str) -> str:
        return self._responses.pop(0)


def test_report_marks_docs_rejected_by_empty_evidence(tmp_path: Path) -> None:
    app = _build_app(
        tmp_path,
        [
            _event_result(confirmed=True, with_evidence=False),
        ],
    )

    artifacts = app.verify(
        event_id=1,
        output_dir=tmp_path / "output",
        primary_model="primary",
        audit_model="audit",
        export_xlsx=False,
    )

    assert artifacts.report.docs_rejected_by_empty_evidence == ["doc.pdf"]
    assert artifacts.report.diagnostic_stage == "doc_level"


def test_report_marks_ocr_missing(tmp_path: Path) -> None:
    app = _build_app(
        tmp_path,
        [],
        summary_repository=FakeSummaryRepository(date_text=None),
        with_ocr=False,
    )

    artifacts = app.verify(
        event_id=1,
        output_dir=tmp_path / "output",
        primary_model="primary",
        audit_model="audit",
        export_xlsx=False,
    )

    assert artifacts.report.diagnostic_stage == "doc_level"
    assert artifacts.report.diagnostic_reason == "OCR отсутствует, документ не анализировался"


def test_report_marks_deadline_late_without_changing_supporting_files(tmp_path: Path) -> None:
    app = _build_app(
        tmp_path,
        [
            _event_result(confirmed=True, with_evidence=True),
        ],
        summary_repository=FakeSummaryRepository(date_text="Дата документа: 10.01.2026"),
    )

    artifacts = app.verify(
        event_id=1,
        output_dir=tmp_path / "output",
        primary_model="primary",
        audit_model="audit",
        export_xlsx=False,
    )

    assert artifacts.report.supporting_files == ["doc.pdf"]
    assert artifacts.report.event_deadline_status == "late"
    assert artifacts.report.date_late_files == ["doc.pdf"]


def _build_app(
    tmp_path: Path,
    responses: list[str],
    *,
    summary_repository: FakeSummaryRepository | None = None,
    with_ocr: bool = True,
) -> VerificationApp:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)
    llm = SequencedLlmClient(responses)
    prompt_loader = PromptLoader(prompts_dir)
    repo = summary_repository or FakeSummaryRepository()
    documents_repo = repo if with_ocr else SummaryOnlyRepository(date_text=repo._date_text)
    return VerificationApp(
        event_repository=FakeEventRepository(),
        summary_repository=documents_repo,
        target_builder=TargetBuilder(prompt_loader, llm, "primary"),
        document_ranking_service=DocumentRankingService(prompt_loader, llm, "ranking"),
        event_verifier=EventVerifier(prompt_loader, llm, "primary"),
        phr_verifier=PhrVerifier(prompt_loader, llm, "primary"),
        audit_service=AuditService(prompt_loader, llm, "audit"),
        deadline_enrichment_service=DeadlineEnrichmentService(summary_repository=documents_repo),
    )


class SummaryOnlyRepository(FakeSummaryRepository):
    def list_event_documents(self, event_id: int) -> list[DocumentSummary]:
        return [
            DocumentSummary(
                document_id="doc-1",
                file_name="doc.pdf",
                evidence_text="summary text",
                evidence_source="summary",
                summary_text="summary text",
            )
        ]


def _event_result(*, confirmed: bool, with_evidence: bool) -> str:
    return json.dumps(
        {
            "document_id": "doc-1",
            "file_name": "doc.pdf",
            "fact_status": "подтверждено" if confirmed else "не подтверждено",
            "reasoning": "Подтверждение найдено." if confirmed else "Подтверждение не найдено.",
            "matched_action": "Событие" if confirmed else None,
            "matched_subject": "Описание" if confirmed else None,
            "completion_signal": "выполнено" if confirmed else None,
            "observed_value": None,
            "observed_unit": None,
            "comparison_result": "not_applicable" if confirmed else "insufficient_data",
            "evidence_quote": "выполнено" if with_evidence else None,
            "reasoning_trace": {
                "reason_codes": ["mentions_completion_fact"] if confirmed else ["insufficient_evidence"],
                "evidence_items": (
                    [
                        {
                            "quote": "выполнено",
                            "page": None,
                            "source": "ocr",
                            "why_relevant": "Direct evidence.",
                        }
                    ]
                    if with_evidence
                    else []
                ),
                "missing_requirements": [] if with_evidence else ["explicit evidence"],
                "short_rationale": "trace",
                "confidence": "high" if with_evidence else "low",
            },
        }
    )
