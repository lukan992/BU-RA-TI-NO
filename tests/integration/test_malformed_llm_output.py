from __future__ import annotations

from pathlib import Path

import pytest

from buratino.app import VerificationApp
from buratino.audit.service import AuditService
from buratino.llm.prompt_loader import PromptLoader
from buratino.models.domain import DocumentSummary, EventRecord, PhrRecord
from buratino.models.errors import LlmOutputError
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
            event_name="Событие",
            event_description="Описание",
            planned_value=0,
            planned_unit="шт",
        )

    def get_event_phr(self, event_id: int) -> PhrRecord:
        return PhrRecord(event_id=event_id, phr_name="ПХР", phr_value_2025=1, phr_unit="шт")


class FakeSummaryRepository:
    def list_event_documents(self, event_id: int) -> list[DocumentSummary]:
        return [
            DocumentSummary(
                document_id="1",
                file_name="doc.pdf",
                evidence_text="summary",
                evidence_source="summary",
                summary_text="summary",
            )
        ]


class BrokenLlmClient:
    def generate_json(self, *, model: str, prompt: str) -> str:
        return "{bad json"


class RecordingBrokenLlmClient:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate_json(self, *, model: str, prompt: str) -> str:
        self.prompts.append(prompt)
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
        document_ranking_service=DocumentRankingService(prompt_loader, BrokenLlmClient(), "ranking"),
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


def test_malformed_ocr_output_does_not_fallback_to_summary(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    class OcrFirstSummaryRepository:
        def list_event_documents(self, event_id: int) -> list[DocumentSummary]:
            return [
                DocumentSummary(
                    document_id="1",
                    file_name="doc.pdf",
                evidence_text="ocr text",
                evidence_source="ocr",
                ocr_text="ocr text",
                summary_text="summary text",
                ocr_parts=("ocr text",),
            )
        ]

    llm = RecordingBrokenLlmClient()
    prompt_loader = PromptLoader(prompts_dir)
    app = VerificationApp(
        event_repository=FakeEventRepository(),
        summary_repository=OcrFirstSummaryRepository(),
        target_builder=TargetBuilder(prompt_loader, llm, "primary"),
        document_ranking_service=DocumentRankingService(prompt_loader, llm, "ranking"),
        event_verifier=EventVerifier(prompt_loader, llm, "primary"),
        phr_verifier=PhrVerifier(prompt_loader, llm, "primary"),
        audit_service=AuditService(prompt_loader, llm, "audit"),
    )

    with pytest.raises(LlmOutputError, match="Malformed JSON"):
        app.verify(
            event_id=1,
            output_dir=tmp_path / "output",
            primary_model="primary",
            audit_model="audit",
            export_xlsx=False,
        )

    assert len(llm.prompts) == 1
    assert "\"evidence_source\": \"ocr\"" in llm.prompts[0]


def test_malformed_chunk_output_does_not_fallback_to_summary(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    class ChunkedOcrRepository:
        def list_event_documents(self, event_id: int) -> list[DocumentSummary]:
            return [
                DocumentSummary(
                    document_id="1",
                    file_name="doc.pdf",
                    evidence_text="page 1\n\npage 2",
                    evidence_source="ocr",
                    ocr_text="page 1\n\npage 2",
                    summary_text="summary text",
                    ocr_parts=("page 1", "page 2"),
                )
            ]

    class ChunkMalformedLlmClient:
        def __init__(self) -> None:
            self.prompts: list[str] = []
            self.calls = 0

        def generate_json(self, *, model: str, prompt: str) -> str:
            self.prompts.append(prompt)
            self.calls += 1
            if self.calls == 1:
                from buratino.models.errors import RepositoryError

                raise RepositoryError("LLM request failed: maximum context length exceeded")
            return "{bad json"

    llm = ChunkMalformedLlmClient()
    prompt_loader = PromptLoader(prompts_dir)
    app = VerificationApp(
        event_repository=FakeEventRepository(),
        summary_repository=ChunkedOcrRepository(),
        target_builder=TargetBuilder(prompt_loader, llm, "primary"),
        document_ranking_service=DocumentRankingService(prompt_loader, llm, "ranking"),
        event_verifier=EventVerifier(prompt_loader, llm, "primary", OcrChunker(20, 5, 10)),
        phr_verifier=PhrVerifier(prompt_loader, llm, "primary", OcrChunker(20, 5, 10)),
        audit_service=AuditService(prompt_loader, llm, "audit"),
    )

    with pytest.raises(LlmOutputError, match="Malformed JSON"):
        app.verify(
            event_id=1,
            output_dir=tmp_path / "output",
            primary_model="primary",
            audit_model="audit",
            export_xlsx=False,
        )

    assert len(llm.prompts) == 2
    assert "\"evidence_source\": \"summary\"" not in "".join(llm.prompts)


def test_malformed_ranking_output_bubbles_up_before_document_analysis(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    class ManyDocumentsRepository:
        def list_event_documents(self, event_id: int) -> list[DocumentSummary]:
            return [
                DocumentSummary(document_id="1", file_name="doc-1.pdf", evidence_text="ocr 1", evidence_source="ocr", summary_text="summary 1"),
                DocumentSummary(document_id="2", file_name="doc-2.pdf", evidence_text="ocr 2", evidence_source="ocr", summary_text="summary 2"),
            ]

    llm = RecordingBrokenLlmClient()
    prompt_loader = PromptLoader(prompts_dir)
    app = VerificationApp(
        event_repository=FakeEventRepository(),
        summary_repository=ManyDocumentsRepository(),
        target_builder=TargetBuilder(prompt_loader, llm, "primary"),
        document_ranking_service=DocumentRankingService(prompt_loader, llm, "ranking"),
        event_verifier=EventVerifier(prompt_loader, llm, "primary"),
        phr_verifier=PhrVerifier(prompt_loader, llm, "primary"),
        audit_service=AuditService(prompt_loader, llm, "audit"),
    )

    with pytest.raises(LlmOutputError, match="Malformed JSON"):
        app.verify(
            event_id=1,
            output_dir=tmp_path / "output",
            primary_model="primary",
            audit_model="audit",
            export_xlsx=False,
            max_documents_to_analyze=1,
        )

    assert len(llm.prompts) == 1


def test_summary_overflow_recovers_with_chunked_summary(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    class SummaryOnlyRepository:
        def list_event_documents(self, event_id: int) -> list[DocumentSummary]:
            return [
                DocumentSummary(
                    document_id="1",
                    file_name="doc.pdf",
                    evidence_text="page 1\n\npage 2",
                    evidence_source="summary",
                    summary_text="page 1\n\npage 2",
                )
            ]

    class OverflowThenMalformedLlmClient:
        def __init__(self) -> None:
            self.prompts: list[str] = []
            self.calls = 0

        def generate_json(self, *, model: str, prompt: str) -> str:
            self.prompts.append(prompt)
            self.calls += 1
            if self.calls == 1:
                from buratino.models.errors import RepositoryError

                raise RepositoryError("LLM request failed: maximum context length exceeded")
            return "{bad json"

    llm = OverflowThenMalformedLlmClient()
    prompt_loader = PromptLoader(prompts_dir)
    app = VerificationApp(
        event_repository=FakeEventRepository(),
        summary_repository=SummaryOnlyRepository(),
        target_builder=TargetBuilder(prompt_loader, llm, "primary"),
        document_ranking_service=DocumentRankingService(prompt_loader, llm, "ranking"),
        event_verifier=EventVerifier(prompt_loader, llm, "primary", OcrChunker(8, 2, 10)),
        phr_verifier=PhrVerifier(prompt_loader, llm, "primary", OcrChunker(8, 2, 10)),
        audit_service=AuditService(prompt_loader, llm, "audit"),
    )

    with pytest.raises(LlmOutputError, match="Malformed JSON"):
        app.verify(
            event_id=1,
            output_dir=tmp_path / "output",
            primary_model="primary",
            audit_model="audit",
            export_xlsx=False,
        )

    assert len(llm.prompts) == 2
    assert "\"evidence_source\": \"summary\"" in llm.prompts[1]
