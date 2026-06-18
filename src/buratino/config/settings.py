"""Application settings loader."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from buratino.config.errors import ConfigurationError

REQUIRED_PROMPT_FILES = (
    "document_ranking.md",
    "event_fact_summary.md",
    "phr_fact_summary.md",
    "logic_audit.md",
    "event_type_resolution.md",
    "confirming_documents_relation.md",
)


def _load_dotenv(env_file: Path) -> None:
    if not env_file.exists() or not env_file.is_file():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        key, separator, value = line.partition("=")
        if not separator:
            continue

        env_name = key.strip()
        if not env_name:
            continue

        os.environ.setdefault(env_name, value.strip().strip("\"'"))


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _require_env(name: str) -> str:
    value = _optional_env(name)
    if value is None:
        raise ConfigurationError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class Settings:
    """Validated runtime configuration."""

    ranking_model: str
    primary_model: str
    audit_model: str
    main_database_url: str
    runtime_database_url: str
    main_db_schema: str
    runtime_db_schema: str
    prompts_dir: Path
    output_dir: Path
    llm_backend: str
    llm_api_base: str | None
    llm_api_key: str | None
    llm_timeout_seconds: float
    llm_temperature: float
    llm_max_tokens: int | None
    event_max_concurrency: int
    ranking_batch_size: int
    ranking_summary_max_chars: int
    max_documents_to_analyze: int | None
    ocr_chunk_max_chars: int
    ocr_chunk_overlap_chars: int
    ocr_chunk_max_chunks: int
    confirming_relation_max_text_chars: int
    confirming_relation_batch_size: int
    evidence_trace_enabled: bool
    reasoning_trace_mode: str
    reasoning_trace_max_items: int
    short_rationale_max_chars: int
    evidence_quote_max_chars: int
    log_level: str
    required_prompt_files: tuple[str, ...] = REQUIRED_PROMPT_FILES

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> "Settings":
        _load_dotenv(Path(env_file))

        ranking_model = _require_env("RANKING_MODEL")
        primary_model = _require_env("PRIMARY_MODEL")
        audit_model = _require_env("AUDIT_MODEL")

        database_url = _optional_env("DATABASE_URL")
        main_database_url = _optional_env("MAIN_DATABASE_URL") or database_url
        runtime_database_url = _optional_env("RUNTIME_DATABASE_URL") or database_url

        if main_database_url is None:
            raise ConfigurationError(
                "Missing required environment variable: MAIN_DATABASE_URL "
                "(or fallback DATABASE_URL)"
            )
        if runtime_database_url is None:
            raise ConfigurationError(
                "Missing required environment variable: RUNTIME_DATABASE_URL "
                "(or fallback DATABASE_URL)"
            )

        prompts_dir = Path(_optional_env("PROMPTS_DIR") or "prompts")
        output_dir = Path(_optional_env("OUTPUT_DIR") or "output")
        main_db_schema = _optional_env("MAIN_DB_SCHEMA") or "public"
        runtime_db_schema = _optional_env("RUNTIME_DB_SCHEMA") or "public"
        llm_backend = (_optional_env("LLM_BACKEND") or "litellm").lower()
        llm_api_base = _optional_env("LLM_API_BASE")
        llm_api_key = _optional_env("LLM_API_KEY")
        llm_timeout_raw = _optional_env("LLM_TIMEOUT_SECONDS") or "120"
        llm_temperature_raw = _optional_env("LLM_TEMPERATURE") or "0"
        llm_max_tokens_raw = _optional_env("LLM_MAX_TOKENS")
        event_max_concurrency_raw = _optional_env("EVENT_MAX_CONCURRENCY") or "3"
        ranking_batch_size_raw = _optional_env("RANKING_BATCH_SIZE") or "5"
        ranking_summary_max_chars_raw = _optional_env("RANKING_SUMMARY_MAX_CHARS") or "6000"
        max_documents_raw = _optional_env("MAX_DOCUMENTS_TO_ANALYZE")
        ocr_chunk_max_chars_raw = _optional_env("OCR_CHUNK_MAX_CHARS") or "40000"
        ocr_chunk_overlap_chars_raw = _optional_env("OCR_CHUNK_OVERLAP_CHARS") or "1500"
        ocr_chunk_max_chunks_raw = _optional_env("OCR_CHUNK_MAX_CHUNKS") or "120"
        confirming_relation_max_text_chars_raw = _optional_env("CONFIRMING_RELATION_MAX_TEXT_CHARS") or "6000"
        confirming_relation_batch_size_raw = _optional_env("CONFIRMING_RELATION_BATCH_SIZE") or "5"
        evidence_trace_enabled_raw = (_optional_env("EVIDENCE_TRACE_ENABLED") or "true").lower()
        reasoning_trace_mode = _optional_env("REASONING_TRACE_MODE") or "structured"
        reasoning_trace_max_items_raw = _optional_env("REASONING_TRACE_MAX_ITEMS") or "5"
        short_rationale_max_chars_raw = _optional_env("SHORT_RATIONALE_MAX_CHARS") or "300"
        evidence_quote_max_chars_raw = _optional_env("EVIDENCE_QUOTE_MAX_CHARS") or "500"
        log_level = (_optional_env("LOG_LEVEL") or "INFO").upper()

        try:
            llm_timeout_seconds = float(llm_timeout_raw)
        except ValueError as exc:
            raise ConfigurationError("LLM_TIMEOUT_SECONDS must be a number.") from exc

        try:
            llm_temperature = float(llm_temperature_raw)
        except ValueError as exc:
            raise ConfigurationError("LLM_TEMPERATURE must be a number.") from exc

        if llm_timeout_seconds <= 0:
            raise ConfigurationError("LLM_TIMEOUT_SECONDS must be positive.")
        if not 0 <= llm_temperature <= 2:
            raise ConfigurationError("LLM_TEMPERATURE must be between 0 and 2.")

        llm_max_tokens: int | None = None
        if llm_max_tokens_raw is not None:
            try:
                llm_max_tokens = int(llm_max_tokens_raw)
            except ValueError as exc:
                raise ConfigurationError("LLM_MAX_TOKENS must be an integer.") from exc
            if llm_max_tokens <= 0:
                raise ConfigurationError("LLM_MAX_TOKENS must be positive.")

        try:
            event_max_concurrency = int(event_max_concurrency_raw)
        except ValueError as exc:
            raise ConfigurationError("EVENT_MAX_CONCURRENCY must be an integer.") from exc
        if event_max_concurrency <= 0:
            raise ConfigurationError("EVENT_MAX_CONCURRENCY must be positive.")

        try:
            ranking_batch_size = int(ranking_batch_size_raw)
        except ValueError as exc:
            raise ConfigurationError("RANKING_BATCH_SIZE must be an integer.") from exc
        if ranking_batch_size <= 0:
            raise ConfigurationError("RANKING_BATCH_SIZE must be positive.")

        try:
            ranking_summary_max_chars = int(ranking_summary_max_chars_raw)
        except ValueError as exc:
            raise ConfigurationError("RANKING_SUMMARY_MAX_CHARS must be an integer.") from exc
        if ranking_summary_max_chars <= 0:
            raise ConfigurationError("RANKING_SUMMARY_MAX_CHARS must be positive.")

        max_documents_to_analyze: int | None = None
        if max_documents_raw is not None:
            try:
                max_documents_to_analyze = int(max_documents_raw)
            except ValueError as exc:
                raise ConfigurationError("MAX_DOCUMENTS_TO_ANALYZE must be an integer.") from exc
            if max_documents_to_analyze <= 0:
                raise ConfigurationError("MAX_DOCUMENTS_TO_ANALYZE must be positive.")

        try:
            ocr_chunk_max_chars = int(ocr_chunk_max_chars_raw)
        except ValueError as exc:
            raise ConfigurationError("OCR_CHUNK_MAX_CHARS must be an integer.") from exc
        if ocr_chunk_max_chars <= 0:
            raise ConfigurationError("OCR_CHUNK_MAX_CHARS must be positive.")

        try:
            ocr_chunk_overlap_chars = int(ocr_chunk_overlap_chars_raw)
        except ValueError as exc:
            raise ConfigurationError("OCR_CHUNK_OVERLAP_CHARS must be an integer.") from exc
        if ocr_chunk_overlap_chars <= 0:
            raise ConfigurationError("OCR_CHUNK_OVERLAP_CHARS must be positive.")
        if ocr_chunk_overlap_chars >= ocr_chunk_max_chars:
            raise ConfigurationError("OCR_CHUNK_OVERLAP_CHARS must be less than OCR_CHUNK_MAX_CHARS.")

        try:
            ocr_chunk_max_chunks = int(ocr_chunk_max_chunks_raw)
        except ValueError as exc:
            raise ConfigurationError("OCR_CHUNK_MAX_CHUNKS must be an integer.") from exc
        if ocr_chunk_max_chunks <= 0:
            raise ConfigurationError("OCR_CHUNK_MAX_CHUNKS must be positive.")

        try:
            confirming_relation_max_text_chars = int(confirming_relation_max_text_chars_raw)
        except ValueError as exc:
            raise ConfigurationError("CONFIRMING_RELATION_MAX_TEXT_CHARS must be an integer.") from exc
        if confirming_relation_max_text_chars <= 0:
            raise ConfigurationError("CONFIRMING_RELATION_MAX_TEXT_CHARS must be positive.")

        try:
            confirming_relation_batch_size = int(confirming_relation_batch_size_raw)
        except ValueError as exc:
            raise ConfigurationError("CONFIRMING_RELATION_BATCH_SIZE must be an integer.") from exc
        if confirming_relation_batch_size <= 0:
            raise ConfigurationError("CONFIRMING_RELATION_BATCH_SIZE must be positive.")

        if evidence_trace_enabled_raw not in {"true", "false"}:
            raise ConfigurationError("EVIDENCE_TRACE_ENABLED must be true or false.")
        evidence_trace_enabled = evidence_trace_enabled_raw == "true"

        try:
            reasoning_trace_max_items = int(reasoning_trace_max_items_raw)
        except ValueError as exc:
            raise ConfigurationError("REASONING_TRACE_MAX_ITEMS must be an integer.") from exc
        if reasoning_trace_max_items <= 0:
            raise ConfigurationError("REASONING_TRACE_MAX_ITEMS must be positive.")

        try:
            short_rationale_max_chars = int(short_rationale_max_chars_raw)
        except ValueError as exc:
            raise ConfigurationError("SHORT_RATIONALE_MAX_CHARS must be an integer.") from exc
        if short_rationale_max_chars <= 0:
            raise ConfigurationError("SHORT_RATIONALE_MAX_CHARS must be positive.")

        try:
            evidence_quote_max_chars = int(evidence_quote_max_chars_raw)
        except ValueError as exc:
            raise ConfigurationError("EVIDENCE_QUOTE_MAX_CHARS must be an integer.") from exc
        if evidence_quote_max_chars <= 0:
            raise ConfigurationError("EVIDENCE_QUOTE_MAX_CHARS must be positive.")

        if not prompts_dir.exists() or not prompts_dir.is_dir():
            raise ConfigurationError(f"Prompts directory does not exist: {prompts_dir}")

        missing_prompt_files = [
            file_name for file_name in REQUIRED_PROMPT_FILES if not (prompts_dir / file_name).is_file()
        ]
        if missing_prompt_files:
            missing = ", ".join(missing_prompt_files)
            raise ConfigurationError(
                f"Prompts directory is missing required prompt files: {missing}"
            )

        return cls(
            ranking_model=ranking_model,
            primary_model=primary_model,
            audit_model=audit_model,
            main_database_url=main_database_url,
            runtime_database_url=runtime_database_url,
            main_db_schema=main_db_schema,
            runtime_db_schema=runtime_db_schema,
            prompts_dir=prompts_dir,
            output_dir=output_dir,
            llm_backend=llm_backend,
            llm_api_base=llm_api_base,
            llm_api_key=llm_api_key,
            llm_timeout_seconds=llm_timeout_seconds,
            llm_temperature=llm_temperature,
            llm_max_tokens=llm_max_tokens,
            event_max_concurrency=event_max_concurrency,
            ranking_batch_size=ranking_batch_size,
            ranking_summary_max_chars=ranking_summary_max_chars,
            max_documents_to_analyze=max_documents_to_analyze,
            ocr_chunk_max_chars=ocr_chunk_max_chars,
            ocr_chunk_overlap_chars=ocr_chunk_overlap_chars,
            ocr_chunk_max_chunks=ocr_chunk_max_chunks,
            confirming_relation_max_text_chars=confirming_relation_max_text_chars,
            confirming_relation_batch_size=confirming_relation_batch_size,
            evidence_trace_enabled=evidence_trace_enabled,
            reasoning_trace_mode=reasoning_trace_mode,
            reasoning_trace_max_items=reasoning_trace_max_items,
            short_rationale_max_chars=short_rationale_max_chars,
            evidence_quote_max_chars=evidence_quote_max_chars,
            log_level=log_level,
            required_prompt_files=REQUIRED_PROMPT_FILES,
        )
