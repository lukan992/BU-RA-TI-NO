from __future__ import annotations

import json
from pathlib import Path

from buratino.app import VerificationApp
from buratino.audit.service import AuditService
from buratino.llm.prompt_loader import PromptLoader
from buratino.models.domain import DocumentSummary, EventRecord, PhrRecord
from buratino.models.errors import RepositoryError
from buratino.target_builder.service import TargetBuilder
from buratino.verifier.document_ranking import DocumentRankingService
from buratino.verifier.event_verifier import EventVerifier
from buratino.verifier.ocr_chunking import OcrChunker
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
        return [
            DocumentSummary(
                document_id="doc-1",
                file_name="report.pdf",
                evidence_text="ocr text",
                evidence_source="ocr",
                ocr_text="ocr text",
                summary_text="summary text",
                ocr_parts=("ocr text",),
            )
        ]


class RecordingLlmClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.prompts: list[str] = []

    def generate_json(self, *, model: str, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._responses.pop(0)


class SequencedFallbackLlmClient:
    def __init__(self, items: list[object]) -> None:
        self._items = items
        self.prompts: list[str] = []

    def generate_json(self, *, model: str, prompt: str) -> str:
        self.prompts.append(prompt)
        item = self._items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_ocr_fallback_passes_ocr_evidence_to_prompts(tmp_path: Path) -> None:
    app, llm = _build_app(
        tmp_path,
        [
            _event_result(False, None),
            _phr_result(False, None),
            _audit_result("не подтверждено", "не подтверждено"),
        ],
    )

    artifacts = app.verify(
        event_id=1,
        output_dir=tmp_path / "output",
        primary_model="primary",
        audit_model="audit",
        export_xlsx=False,
    )

    assert artifacts.report.event_reasoning.count(".") >= 3
    assert "chunk" not in artifacts.report.event_reasoning.lower()
    assert "\"evidence_source\": \"ocr\"" in llm.prompts[0]
    assert "\"evidence_text\": \"ocr text\"" in llm.prompts[0]


def test_context_overflow_retries_with_summary_when_chunking_is_skipped(tmp_path: Path) -> None:
    class MultiPartSummaryRepository(FakeSummaryRepository):
        def list_event_documents(self, event_id: int) -> list[DocumentSummary]:
            return [
                DocumentSummary(
                    document_id="doc-1",
                    file_name="report.pdf",
                    evidence_text="page 1\n\npage 2",
                    evidence_source="ocr",
                    ocr_text="page 1\n\npage 2",
                    summary_text="summary text",
                    ocr_parts=("page 1", "page 2"),
                )
            ]

    app, llm = _build_app(
        tmp_path,
        [
            RepositoryError("LLM request failed: maximum context length exceeded"),
            _event_result(True, "мероприятие выполнено", comparison_result="not_applicable"),
            RepositoryError("LLM request failed: prompt is too long"),
            _phr_result(True, "10 участников"),
            _audit_result("подтверждено", "подтверждено", ["report.pdf"]),
        ],
        summary_repository=MultiPartSummaryRepository(),
        event_chunker=OcrChunker(10, 3, 1),
        phr_chunker=OcrChunker(10, 3, 1),
    )

    artifacts = app.verify(
        event_id=1,
        output_dir=tmp_path / "output",
        primary_model="primary",
        audit_model="audit",
        export_xlsx=False,
    )

    assert artifacts.report.event_fact_status == "подтверждено"
    assert artifacts.report.phr_fact_status == "подтверждено"
    assert "\"evidence_source\": \"summary\"" in llm.prompts[1]
    assert "\"evidence_text\": \"summary text\"" in llm.prompts[1]


def test_context_overflow_retries_with_chunked_ocr_before_summary(tmp_path: Path) -> None:
    class ChunkedSummaryRepository(FakeSummaryRepository):
        def list_event_documents(self, event_id: int) -> list[DocumentSummary]:
            return [
                DocumentSummary(
                    document_id="doc-1",
                    file_name="report.pdf",
                    evidence_text="page 1\n\npage 2",
                    evidence_source="ocr",
                    ocr_text="page 1\n\npage 2",
                    summary_text="summary text",
                    ocr_parts=("page 1", "page 2"),
                )
            ]

    app, llm = _build_app(
        tmp_path,
        [
            RepositoryError("LLM request failed: maximum context length exceeded"),
            _event_result(False, None),
            _event_result(True, "мероприятие выполнено", comparison_result="not_applicable"),
            RepositoryError("LLM request failed: prompt is too long"),
            _phr_result(False, None),
            _phr_result(True, "10 участников"),
            _audit_result("подтверждено", "подтверждено", ["report.pdf"]),
        ],
        summary_repository=ChunkedSummaryRepository(),
        event_chunker=OcrChunker(10, 3, 10),
        phr_chunker=OcrChunker(10, 3, 10),
    )

    artifacts = app.verify(
        event_id=1,
        output_dir=tmp_path / "output",
        primary_model="primary",
        audit_model="audit",
        export_xlsx=False,
    )

    assert artifacts.report.event_fact_status == "подтверждено"
    assert artifacts.report.phr_fact_status == "подтверждено"
    assert "chunk 2/2" in artifacts.report.event_documents[0].reasoning
    assert "chunk 2/2" in artifacts.report.phr_documents[0].reasoning
    assert "\"evidence_source\": \"summary\"" not in "".join(llm.prompts[:4])


def test_chunked_ocr_all_negative_keeps_document_not_confirmed(tmp_path: Path) -> None:
    class ChunkedSummaryRepository(FakeSummaryRepository):
        def list_event_documents(self, event_id: int) -> list[DocumentSummary]:
            return [
                DocumentSummary(
                    document_id="doc-1",
                    file_name="report.pdf",
                    evidence_text="page 1\n\npage 2",
                    evidence_source="ocr",
                    ocr_text="page 1\n\npage 2",
                    summary_text="summary text",
                    ocr_parts=("page 1", "page 2"),
                )
            ]

    app, _ = _build_app(
        tmp_path,
        [
            RepositoryError("LLM request failed: maximum context length exceeded"),
            _event_result(False, None),
            _event_result(False, None),
            RepositoryError("LLM request failed: prompt is too long"),
            _phr_result(False, None),
            _phr_result(False, "5 участников", comparison_result="below_target"),
            _audit_result("не подтверждено", "не подтверждено"),
        ],
        summary_repository=ChunkedSummaryRepository(),
        event_chunker=OcrChunker(10, 3, 10),
        phr_chunker=OcrChunker(10, 3, 10),
    )

    artifacts = app.verify(
        event_id=1,
        output_dir=tmp_path / "output",
        primary_model="primary",
        audit_model="audit",
        export_xlsx=False,
    )

    assert artifacts.report.event_fact_status == "не подтверждено"
    assert artifacts.report.phr_fact_status == "не подтверждено"
    assert "chunk 1/2" in artifacts.report.event_documents[0].reasoning
    assert "chunk 1/2" in artifacts.report.phr_documents[0].reasoning


def _build_app(
    tmp_path: Path,
    responses: list[object],
    *,
    summary_repository=None,
    event_chunker=None,
    phr_chunker=None,
) -> tuple[VerificationApp, RecordingLlmClient | SequencedFallbackLlmClient]:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)
    llm = responses if isinstance(responses, (RecordingLlmClient, SequencedFallbackLlmClient)) else None
    if llm is None:
        if any(isinstance(item, Exception) for item in responses):
            llm = SequencedFallbackLlmClient(responses)
        else:
            llm = RecordingLlmClient(responses)  # type: ignore[arg-type]
    prompt_loader = PromptLoader(prompts_dir)
    app = VerificationApp(
        event_repository=FakeEventRepository(),
        summary_repository=summary_repository or FakeSummaryRepository(),
        target_builder=TargetBuilder(prompt_loader, llm, "primary"),
        document_ranking_service=DocumentRankingService(prompt_loader, llm, "ranking"),
        event_verifier=EventVerifier(prompt_loader, llm, "primary", event_chunker or OcrChunker(40000, 1500, 120)),
        phr_verifier=PhrVerifier(prompt_loader, llm, "primary", phr_chunker or OcrChunker(40000, 1500, 120)),
        audit_service=AuditService(prompt_loader, llm, "audit"),
    )
    return app, llm


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


def _event_result(confirmed: bool, quote: str | None, *, comparison_result: str = "insufficient_data") -> str:
    return json.dumps(
        {
            "document_id": "doc-1",
            "file_name": "report.pdf",
            "fact_status": "подтверждено" if confirmed else "не подтверждено",
            "reasoning": "OCR chunk использован. Есть прямой факт выполнения. Поэтому статус подтвержден."
            if confirmed
            else "OCR chunk использован. Прямого факта выполнения нет. Поэтому статус не подтвержден.",
            "matched_action": "Проверить мероприятие" if confirmed else None,
            "matched_subject": "Факт выполнения" if confirmed else None,
            "completion_signal": "выполнено" if confirmed else None,
            "observed_value": None,
            "observed_unit": None,
            "comparison_result": comparison_result,
            "evidence_quote": quote,
            "reasoning_trace": _reasoning_trace(confirmed, quote),
        }
    )


def _phr_result(confirmed: bool, quote: str | None, *, comparison_result: str = "meets_target") -> str:
    return json.dumps(
        {
            "document_id": "doc-1",
            "file_name": "report.pdf",
            "phr_fact_status": "подтверждено" if confirmed else "не подтверждено",
            "reasoning": "OCR chunk использован. Метрика и характеристика подтверждены. Поэтому статус подтвержден."
            if confirmed
            else "OCR chunk использован. Метрика не подтверждена. Поэтому статус не подтвержден.",
            "metric_matched": "Количество участников" if quote is not None else None,
            "characteristic_explicitly_matched": confirmed,
            "quantity_refers_to_metric_object": confirmed,
            "observed_value": 10 if confirmed else (5 if quote is not None else None),
            "observed_unit": "чел" if quote is not None else None,
            "comparison_result": comparison_result,
            "evidence_quote": quote,
            "reasoning_trace": _reasoning_trace(confirmed, quote),
        }
    )


def _audit_result(event_status: str, phr_status: str, supporting_files: list[str] | None = None) -> str:
    return json.dumps(
        {
            "audit_result": "pass",
            "rule_violations": [],
            "final_event_fact_status": event_status,
            "final_phr_fact_status": phr_status,
            "final_supporting_files": supporting_files or [],
        }
    )
