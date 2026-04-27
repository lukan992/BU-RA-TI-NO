from __future__ import annotations

from pathlib import Path

import pytest

from buratino.app import VerificationApp
from buratino.audit.service import AuditService
from buratino.llm.prompt_loader import PromptLoader
from buratino.models.domain import DocumentSummary, EventRecord, PhrRecord
from buratino.models.errors import LlmOutputError
from buratino.target_builder.service import TargetBuilder
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
        )

    def get_event_phr(self, event_id: int) -> PhrRecord:
        return PhrRecord(event_id=event_id, phr_name="ПХР", phr_value_2025=1, phr_unit="шт")


class FakeSummaryRepository:
    def list_event_documents(self, event_id: int) -> list[DocumentSummary]:
        return [DocumentSummary(document_id="1", file_name="doc.pdf", evidence_text="summary", evidence_source="summary")]


class BrokenLlmClient:
    def generate_json(self, *, model: str, prompt: str) -> str:
        return "{bad json"


def test_malformed_llm_output_bubbles_up(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    prompt_loader = PromptLoader(prompts_dir)
    app = VerificationApp(
        event_repository=FakeEventRepository(),
        summary_repository=FakeSummaryRepository(),
        target_builder=TargetBuilder(prompt_loader, BrokenLlmClient(), "primary"),
        event_verifier=EventVerifier(prompt_loader, BrokenLlmClient(), "primary"),
        phr_verifier=PhrVerifier(prompt_loader, BrokenLlmClient(), "primary"),
        audit_service=AuditService(prompt_loader, BrokenLlmClient(), "audit"),
    )

    with pytest.raises(LlmOutputError, match="Malformed JSON"):
        app.verify(
            event_id=1,
            output_dir=tmp_path / "output",
            primary_model="primary",
            audit_model="audit",
            export_xlsx=False,
        )
