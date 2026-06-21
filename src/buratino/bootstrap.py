"""Runtime wiring."""

from __future__ import annotations

from buratino.app import VerificationApp
from buratino.audit.service import AuditService
from buratino.config.errors import ConfigurationError
from buratino.config.settings import Settings
from buratino.llm.json_parser import TraceLimits
from buratino.llm.client import LiteLlmClient
from buratino.llm.prompt_loader import PromptLoader
from buratino.repository.events import PostgresEventRepository
from buratino.repository.summaries import PostgresSummaryRepository
from buratino.target_builder.service import TargetBuilder
from buratino.verifier.confirming_documents_relation import ConfirmingDocumentsRelationService
from buratino.verifier.deadline_enrichment import DeadlineEnrichmentService
from buratino.verifier.document_ranking import DocumentRankingService
from buratino.verifier.event_verifier import EventVerifier
from buratino.verifier.ocr_chunking import OcrChunker
from buratino.verifier.phr_verifier import PhrVerifier


def build_app(settings: Settings) -> VerificationApp:
    if settings.llm_backend != "litellm":
        raise ConfigurationError(
            f"Unsupported LLM_BACKEND={settings.llm_backend!r}. Only 'litellm' is supported."
        )

    prompt_loader = PromptLoader(settings.prompts_dir)
    llm_client = LiteLlmClient(
        api_base=settings.llm_api_base,
        api_key=settings.llm_api_key,
        timeout_seconds=settings.llm_timeout_seconds,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
    )
    event_repository = PostgresEventRepository(
        dsn=settings.main_database_url,
        schema=settings.main_db_schema,
    )
    summary_repository = PostgresSummaryRepository(
        dsn=settings.runtime_database_url,
        schema=settings.runtime_db_schema,
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

    return VerificationApp(
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
        audit_service=AuditService(
            prompt_loader=prompt_loader,
            llm_client=llm_client,
            audit_model=settings.audit_model,
        ),
        deadline_enrichment_service=DeadlineEnrichmentService(
            summary_repository=summary_repository,
        ),
        confirming_documents_relation_service=ConfirmingDocumentsRelationService(
            prompt_loader=prompt_loader,
            llm_client=llm_client,
            primary_model=settings.primary_model,
            summary_repository=summary_repository,
            max_text_chars=settings.confirming_relation_max_text_chars,
            batch_size=settings.confirming_relation_batch_size,
            chunker=ocr_chunker,
        ),
        ranking_enabled=settings.ranking_enabled,
        audit_enabled=settings.audit_enabled,
    )
