from __future__ import annotations

import json
from pathlib import Path

from buratino.app import VerificationApp
from buratino.models.domain import EventRecord, FileEvidence, PhrRecord
from buratino.models.errors import NotFoundError
from buratino.service.analysis import BuratinoAnalysisService
from buratino.target_builder.service import TargetBuilder
from buratino.verifier.document_ranking import DocumentRankingService
from buratino.verifier.event_verifier import EventVerifier
from buratino.verifier.ocr_chunking import OcrChunker
from buratino.verifier.phr_verifier import PhrVerifier
from buratino.llm.prompt_loader import PromptLoader
from conftest import create_prompt_assets


class FakeEventRepository:
    def __init__(
        self,
        *,
        planned_value: float | None = 2,
        planned_unit: str | None = "ед",
        phr_record: PhrRecord | None = None,
        missing_phr: bool = False,
    ) -> None:
        self._planned_value = planned_value
        self._planned_unit = planned_unit
        self._phr_record = phr_record
        self._missing_phr = missing_phr

    def get_event(self, event_id: int) -> EventRecord:
        return EventRecord(
            event_id=event_id,
            event_name="Построить спортивный объект",
            event_description="Построить объект и ввести его в эксплуатацию",
            planned_value=self._planned_value,
            planned_unit=self._planned_unit,
        )

    def get_event_phr(self, event_id: int) -> PhrRecord:
        if self._missing_phr:
            raise NotFoundError(f"PHR not found for event_id={event_id}")
        if self._phr_record is not None:
            return self._phr_record
        return PhrRecord(
            event_id=event_id,
            phr_name="Количество введенных объектов",
            phr_value_2025=2,
            phr_unit="ед",
        )


class FakeSummaryRepository:
    def __init__(self, files: list[FileEvidence]) -> None:
        self._files = files

    def list_file_evidence(self, event_id: int) -> list[FileEvidence]:
        return list(self._files)

    def list_event_documents(self, event_id: int):
        raise NotImplementedError

    def get_document_date_texts(self, document_ids: list[str]) -> dict[str, str | None]:
        return {document_id: None for document_id in document_ids}


class SequencedLlmClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    def generate_json(self, *, model: str, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._responses:
            raise AssertionError("No more fake LLM responses configured.")
        return self._responses.pop(0)


def build_app(
    tmp_path: Path,
    *,
    responses: list[str],
    files: list[FileEvidence],
    event_repository: FakeEventRepository | None = None,
    ranking_enabled: bool = False,
) -> tuple[VerificationApp, SequencedLlmClient]:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)
    llm = SequencedLlmClient(responses)
    prompt_loader = PromptLoader(prompts_dir)
    service = BuratinoAnalysisService(
        event_repository=event_repository or FakeEventRepository(),
        summary_repository=FakeSummaryRepository(files),
        target_builder=TargetBuilder(prompt_loader, llm, "primary"),
        document_ranking_service=DocumentRankingService(prompt_loader, llm, "ranking"),
        event_verifier=EventVerifier(prompt_loader, llm, "primary", ocr_chunker=OcrChunker(40000, 1500, 120)),
        phr_verifier=PhrVerifier(prompt_loader, llm, "primary", ocr_chunker=OcrChunker(40000, 1500, 120)),
        primary_model="primary",
        ranking_model="ranking",
        audit_model="audit",
        ranking_enabled=ranking_enabled,
        audit_enabled=False,
        date_check_enabled=False,
        summary_verdict_enabled=False,
        pipeline_version="0.1.0",
    )
    return VerificationApp(analysis_service=service), llm


def ocr_file(document_id: str, file_name: str, text: str, *, summary_text: str | None = None) -> FileEvidence:
    return FileEvidence(
        document_id=document_id,
        file_name=file_name,
        evidence_text=text,
        evidence_source="ocr",
        source_table="public.documents+ocr_results",
        ocr_text=text,
        summary_text=summary_text,
        ocr_parts=(text,),
    )


def summary_only_file(document_id: str, file_name: str, text: str) -> FileEvidence:
    return FileEvidence(
        document_id=document_id,
        file_name=file_name,
        evidence_text=None,
        evidence_source="none",
        source_table="public.documents",
        ocr_text=None,
        summary_text=text,
        ocr_parts=(),
    )


def event_result(
    *,
    confirmed: bool,
    comparison_result: str,
    quote: str | None,
    observed_value: int | None = 2,
    observed_unit: str | None = "ед",
) -> str:
    return json.dumps(
        {
            "document_id": "doc-1",
            "file_name": "report-1.pdf",
            "fact_status": "подтверждено" if confirmed else "не подтверждено",
            "reasoning": "event reasoning",
            "matched_action": "построить",
            "matched_subject": "объект",
            "completion_signal": "введено",
            "observed_value": observed_value,
            "observed_unit": observed_unit,
            "comparison_result": comparison_result,
            "evidence_quote": quote,
            "reasoning_trace": {
                "reason_codes": ["mentions_completion_fact"] if confirmed else ["insufficient_evidence"],
                "evidence_items": (
                    [{"quote": quote or "fragment", "page": None, "source": "ocr", "why_relevant": "relevant"}]
                    if quote is not None
                    else []
                ),
                "missing_requirements": [] if confirmed else ["explicit evidence"],
                "short_rationale": "trace",
                "confidence": "high" if confirmed else "low",
            },
        },
        ensure_ascii=False,
    )


def phr_result(*, confirmed: bool, comparison_result: str, quote: str | None, observed_value: int | None = 2) -> str:
    return json.dumps(
        {
            "document_id": "doc-1",
            "file_name": "report-1.pdf",
            "phr_fact_status": "подтверждено" if confirmed else "не подтверждено",
            "reasoning": "phr reasoning",
            "metric_matched": "Количество введенных объектов" if confirmed else None,
            "characteristic_explicitly_matched": confirmed,
            "quantity_refers_to_metric_object": confirmed,
            "observed_value": observed_value if confirmed else None,
            "observed_unit": "ед" if confirmed else None,
            "comparison_result": comparison_result,
            "evidence_quote": quote,
            "reasoning_trace": {
                "reason_codes": ["metric_reached"] if confirmed else ["insufficient_evidence"],
                "evidence_items": (
                    [{"quote": quote or "fragment", "page": None, "source": "ocr", "why_relevant": "relevant"}]
                    if quote is not None
                    else []
                ),
                "missing_requirements": [] if confirmed else ["explicit evidence"],
                "short_rationale": "trace",
                "confidence": "high" if confirmed else "low",
            },
        },
        ensure_ascii=False,
    )
