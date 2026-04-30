"""Runtime wiring."""

from __future__ import annotations

from buratino.app import VerificationApp
from buratino.audit.service import AuditService
from buratino.config.errors import ConfigurationError
from buratino.config.settings import Settings
from buratino.llm.client import LiteLlmClient
from buratino.llm.prompt_loader import PromptLoader
from buratino.repository.events import PostgresEventRepository
from buratino.repository.summaries import PostgresSummaryRepository
from buratino.target_builder.service import TargetBuilder
from buratino.verifier.confirming_documents_relation import ConfirmingDocumentsRelationService
from buratino.verifier.event_verifier import EventVerifier
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

    return VerificationApp(
        event_repository=event_repository,
        summary_repository=summary_repository,
        target_builder=TargetBuilder(
            prompt_loader=prompt_loader,
            llm_client=llm_client,
            primary_model=settings.primary_model,
        ),
        event_verifier=EventVerifier(
            prompt_loader=prompt_loader,
            llm_client=llm_client,
            primary_model=settings.primary_model,
        ),
        phr_verifier=PhrVerifier(
            prompt_loader=prompt_loader,
            llm_client=llm_client,
            primary_model=settings.primary_model,
        ),
        audit_service=AuditService(
            prompt_loader=prompt_loader,
            llm_client=llm_client,
            audit_model=settings.audit_model,
        ),
        confirming_documents_relation_service=ConfirmingDocumentsRelationService(
            prompt_loader=prompt_loader,
            llm_client=llm_client,
            primary_model=settings.primary_model,
            summary_repository=summary_repository,
            max_text_chars=settings.confirming_relation_max_text_chars,
        ),
    )
