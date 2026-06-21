"""Runtime wiring."""

from __future__ import annotations

from buratino.app import VerificationApp
from buratino.config.errors import ConfigurationError
from buratino.config.settings import Settings
from buratino.llm.client import LiteLlmClient
from buratino.llm.fake_client import FakeLlmClient
from buratino.llm.json_parser import TraceLimits
from buratino.llm.prompt_loader import PromptLoader
from buratino.repository.events import PostgresEventRepository
from buratino.repository.summaries import PostgresSummaryRepository
from buratino.service.analysis import BuratinoAnalysisService
from buratino.target_builder.service import TargetBuilder
from buratino.verifier.document_ranking import DocumentRankingService
from buratino.verifier.event_verifier import EventVerifier
from buratino.verifier.ocr_chunking import OcrChunker
from buratino.verifier.phr_verifier import PhrVerifier


def build_analysis_service(settings: Settings) -> BuratinoAnalysisService:
    if settings.llm_backend not in {"litellm", "fake", "openrouter"}:
        raise ConfigurationError(
            f"Unsupported LLM_BACKEND={settings.llm_backend!r}. Supported backends: 'litellm', 'fake', 'openrouter'."
        )

    prompt_loader = PromptLoader(settings.prompts_dir)
    llm_client = (
        FakeLlmClient()
        if settings.llm_backend == "fake" or settings.fake_llm_enabled
        else LiteLlmClient(
            api_base=settings.llm_api_base,
            api_key=settings.llm_api_key,
            timeout_seconds=settings.llm_timeout_seconds,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
    )
    event_repository = PostgresEventRepository(
        dsn=settings.main_database_url,
        schema=settings.main_db_schema,
    )
    summary_repository = PostgresSummaryRepository(
        dsn=settings.runtime_database_url,
        schema=settings.runtime_db_schema,
        evidence_source_mode=settings.evidence_source_mode,
    )
    ocr_chunker = OcrChunker(
        max_chars=settings.ocr_chunk_max_chars,
        overlap_chars=settings.ocr_chunk_overlap_chars,
        max_chunks=settings.ocr_chunk_max_chunks,
    )
    trace_limits = TraceLimits(
        max_items=settings.reasoning_trace_max_items,
        short_rationale_max_chars=settings.short_rationale_max_chars,
        evidence_quote_max_chars=settings.evidence_quote_max_chars,
    )
    return BuratinoAnalysisService(
        event_repository=event_repository,
        summary_repository=summary_repository,
        target_builder=TargetBuilder(
            prompt_loader=prompt_loader,
            llm_client=llm_client,
            primary_model=settings.primary_model,
        ),
        document_ranking_service=DocumentRankingService(
            prompt_loader=prompt_loader,
            llm_client=llm_client,
            ranking_model=settings.ranking_model,
            batch_size=settings.ranking_batch_size,
            summary_max_chars=settings.ranking_summary_max_chars,
        ),
        event_verifier=EventVerifier(
            prompt_loader=prompt_loader,
            llm_client=llm_client,
            primary_model=settings.primary_model,
            evidence_source_mode=settings.evidence_source_mode,
            ocr_chunker=ocr_chunker,
            trace_limits=trace_limits,
        ),
        phr_verifier=PhrVerifier(
            prompt_loader=prompt_loader,
            llm_client=llm_client,
            primary_model=settings.primary_model,
            evidence_source_mode=settings.evidence_source_mode,
            ocr_chunker=ocr_chunker,
            trace_limits=trace_limits,
        ),
        primary_model=settings.primary_model,
        ranking_model=settings.ranking_model,
        audit_model=settings.audit_model,
        ranking_enabled=settings.ranking_enabled,
        audit_enabled=settings.audit_enabled,
        date_check_enabled=settings.date_check_enabled,
        summary_verdict_enabled=settings.summary_verdict_enabled,
        pipeline_version="0.1.0",
    )


def build_app(settings: Settings) -> VerificationApp:
    return VerificationApp(analysis_service=build_analysis_service(settings))
