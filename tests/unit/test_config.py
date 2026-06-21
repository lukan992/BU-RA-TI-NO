from __future__ import annotations

from pathlib import Path

import pytest

from buratino.config.errors import ConfigurationError
from buratino.config.settings import Settings
from conftest import create_prompt_assets


@pytest.fixture(autouse=True)
def clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "RANKING_MODEL",
        "PRIMARY_MODEL",
        "AUDIT_MODEL",
        "DATABASE_URL",
        "MAIN_DATABASE_URL",
        "RUNTIME_DATABASE_URL",
        "MAIN_DB_SCHEMA",
        "RUNTIME_DB_SCHEMA",
        "PROMPTS_DIR",
        "OUTPUT_DIR",
        "LLM_BACKEND",
        "LLM_API_BASE",
        "LLM_API_KEY",
        "LLM_TIMEOUT_SECONDS",
        "LLM_TEMPERATURE",
        "LLM_MAX_TOKENS",
        "EVENT_MAX_CONCURRENCY",
        "RANKING_BATCH_SIZE",
        "RANKING_SUMMARY_MAX_CHARS",
        "MAX_DOCUMENTS_TO_ANALYZE",
        "RANKING_ENABLED",
        "OCR_CHUNK_MAX_CHARS",
        "OCR_CHUNK_OVERLAP_CHARS",
        "OCR_CHUNK_MAX_CHUNKS",
        "EVIDENCE_SOURCE_MODE",
        "AUDIT_ENABLED",
        "CONFIRMING_RELATION_MAX_TEXT_CHARS",
        "CONFIRMING_RELATION_BATCH_SIZE",
        "EVIDENCE_TRACE_ENABLED",
        "REASONING_TRACE_MODE",
        "REASONING_TRACE_MAX_ITEMS",
        "SHORT_RATIONALE_MAX_CHARS",
        "EVIDENCE_QUOTE_MAX_CHARS",
    ):
        monkeypatch.delenv(key, raising=False)


def test_settings_from_env_requires_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAIN_DATABASE_URL", "postgresql://main")
    monkeypatch.setenv("RUNTIME_DATABASE_URL", "postgresql://runtime")

    with pytest.raises(ConfigurationError, match="PRIMARY_MODEL"):
        Settings.from_env(env_file="missing.env")


def test_settings_from_env_uses_database_url_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    monkeypatch.setenv("PRIMARY_MODEL", "primary")
    monkeypatch.setenv("AUDIT_MODEL", "audit")
    monkeypatch.setenv("RANKING_MODEL", "ranking")
    monkeypatch.setenv("DATABASE_URL", "postgresql://shared")
    monkeypatch.setenv("PROMPTS_DIR", str(prompts_dir))

    settings = Settings.from_env(env_file="missing.env")

    assert settings.main_database_url == "postgresql://shared"
    assert settings.runtime_database_url == "postgresql://shared"
    assert settings.prompts_dir == prompts_dir


def test_settings_from_env_requires_existing_prompts_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("PRIMARY_MODEL", "primary")
    monkeypatch.setenv("AUDIT_MODEL", "audit")
    monkeypatch.setenv("RANKING_MODEL", "ranking")
    monkeypatch.setenv("MAIN_DATABASE_URL", "postgresql://main")
    monkeypatch.setenv("RUNTIME_DATABASE_URL", "postgresql://runtime")
    monkeypatch.setenv("PROMPTS_DIR", str(tmp_path / "missing-prompts"))

    with pytest.raises(ConfigurationError, match="Prompts directory does not exist"):
        Settings.from_env(env_file="missing.env")


def test_settings_from_env_requires_prompt_assets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "event_fact_summary.md").write_text("event", encoding="utf-8")

    monkeypatch.setenv("PRIMARY_MODEL", "primary")
    monkeypatch.setenv("AUDIT_MODEL", "audit")
    monkeypatch.setenv("RANKING_MODEL", "ranking")
    monkeypatch.setenv("MAIN_DATABASE_URL", "postgresql://main")
    monkeypatch.setenv("RUNTIME_DATABASE_URL", "postgresql://runtime")
    monkeypatch.setenv("PROMPTS_DIR", str(prompts_dir))

    with pytest.raises(ConfigurationError, match="missing required prompt files"):
        Settings.from_env(env_file="missing.env")


def test_settings_from_env_loads_dotenv_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "PRIMARY_MODEL=primary",
                "AUDIT_MODEL=audit",
                "RANKING_MODEL=ranking",
                "MAIN_DATABASE_URL=postgresql://main",
                "RUNTIME_DATABASE_URL=postgresql://runtime",
                f"PROMPTS_DIR={prompts_dir}",
                "OUTPUT_DIR=custom-output",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings.from_env(env_file=env_file)

    assert settings.primary_model == "primary"
    assert settings.ranking_model == "ranking"
    assert settings.output_dir == Path("custom-output")
    assert settings.llm_timeout_seconds == 120.0
    assert settings.llm_temperature == 0.0
    assert settings.llm_max_tokens is None
    assert settings.event_max_concurrency == 3
    assert settings.ranking_batch_size == 5
    assert settings.ranking_summary_max_chars == 6000
    assert settings.max_documents_to_analyze is None
    assert settings.ocr_chunk_max_chars == 40000
    assert settings.ocr_chunk_overlap_chars == 1500
    assert settings.ocr_chunk_max_chunks == 120
    assert settings.evidence_source_mode == "ocr_first"
    assert settings.ranking_enabled is False
    assert settings.audit_enabled is False
    assert settings.confirming_relation_max_text_chars == 6000
    assert settings.confirming_relation_batch_size == 5
    assert settings.evidence_trace_enabled is True
    assert settings.reasoning_trace_mode == "structured"
    assert settings.reasoning_trace_max_items == 5
    assert settings.short_rationale_max_chars == 300
    assert settings.evidence_quote_max_chars == 500


def test_settings_from_env_validates_temperature_range(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    monkeypatch.setenv("PRIMARY_MODEL", "primary")
    monkeypatch.setenv("AUDIT_MODEL", "audit")
    monkeypatch.setenv("RANKING_MODEL", "ranking")
    monkeypatch.setenv("DATABASE_URL", "postgresql://shared")
    monkeypatch.setenv("PROMPTS_DIR", str(prompts_dir))
    monkeypatch.setenv("LLM_TEMPERATURE", "3")

    with pytest.raises(ConfigurationError, match="LLM_TEMPERATURE must be between 0 and 2"):
        Settings.from_env(env_file="missing.env")


def test_settings_from_env_reads_document_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    monkeypatch.setenv("PRIMARY_MODEL", "primary")
    monkeypatch.setenv("AUDIT_MODEL", "audit")
    monkeypatch.setenv("RANKING_MODEL", "ranking")
    monkeypatch.setenv("DATABASE_URL", "postgresql://shared")
    monkeypatch.setenv("PROMPTS_DIR", str(prompts_dir))
    monkeypatch.setenv("MAX_DOCUMENTS_TO_ANALYZE", "10")

    settings = Settings.from_env(env_file="missing.env")

    assert settings.max_documents_to_analyze == 10


def test_settings_from_env_reads_event_max_concurrency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    monkeypatch.setenv("PRIMARY_MODEL", "primary")
    monkeypatch.setenv("AUDIT_MODEL", "audit")
    monkeypatch.setenv("RANKING_MODEL", "ranking")
    monkeypatch.setenv("DATABASE_URL", "postgresql://shared")
    monkeypatch.setenv("PROMPTS_DIR", str(prompts_dir))
    monkeypatch.setenv("EVENT_MAX_CONCURRENCY", "5")

    settings = Settings.from_env(env_file="missing.env")

    assert settings.event_max_concurrency == 5


def test_settings_from_env_validates_event_max_concurrency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    monkeypatch.setenv("PRIMARY_MODEL", "primary")
    monkeypatch.setenv("AUDIT_MODEL", "audit")
    monkeypatch.setenv("RANKING_MODEL", "ranking")
    monkeypatch.setenv("DATABASE_URL", "postgresql://shared")
    monkeypatch.setenv("PROMPTS_DIR", str(prompts_dir))
    monkeypatch.setenv("EVENT_MAX_CONCURRENCY", "0")

    with pytest.raises(ConfigurationError, match="EVENT_MAX_CONCURRENCY must be positive"):
        Settings.from_env(env_file="missing.env")


def test_settings_from_env_reads_confirming_relation_text_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    monkeypatch.setenv("PRIMARY_MODEL", "primary")
    monkeypatch.setenv("AUDIT_MODEL", "audit")
    monkeypatch.setenv("RANKING_MODEL", "ranking")
    monkeypatch.setenv("DATABASE_URL", "postgresql://shared")
    monkeypatch.setenv("PROMPTS_DIR", str(prompts_dir))
    monkeypatch.setenv("CONFIRMING_RELATION_MAX_TEXT_CHARS", "12000")

    settings = Settings.from_env(env_file="missing.env")

    assert settings.confirming_relation_max_text_chars == 12000


def test_settings_from_env_reads_ranking_overflow_limits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    monkeypatch.setenv("PRIMARY_MODEL", "primary")
    monkeypatch.setenv("AUDIT_MODEL", "audit")
    monkeypatch.setenv("RANKING_MODEL", "ranking")
    monkeypatch.setenv("DATABASE_URL", "postgresql://shared")
    monkeypatch.setenv("PROMPTS_DIR", str(prompts_dir))
    monkeypatch.setenv("RANKING_BATCH_SIZE", "7")
    monkeypatch.setenv("RANKING_SUMMARY_MAX_CHARS", "1234")
    monkeypatch.setenv("CONFIRMING_RELATION_BATCH_SIZE", "4")

    settings = Settings.from_env(env_file="missing.env")

    assert settings.ranking_batch_size == 7
    assert settings.ranking_summary_max_chars == 1234
    assert settings.confirming_relation_batch_size == 4


def test_settings_from_env_reads_ocr_chunk_limits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    monkeypatch.setenv("PRIMARY_MODEL", "primary")
    monkeypatch.setenv("AUDIT_MODEL", "audit")
    monkeypatch.setenv("RANKING_MODEL", "ranking")
    monkeypatch.setenv("DATABASE_URL", "postgresql://shared")
    monkeypatch.setenv("PROMPTS_DIR", str(prompts_dir))
    monkeypatch.setenv("OCR_CHUNK_MAX_CHARS", "50000")
    monkeypatch.setenv("OCR_CHUNK_OVERLAP_CHARS", "2000")
    monkeypatch.setenv("OCR_CHUNK_MAX_CHUNKS", "80")

    settings = Settings.from_env(env_file="missing.env")

    assert settings.ocr_chunk_max_chars == 50000
    assert settings.ocr_chunk_overlap_chars == 2000
    assert settings.ocr_chunk_max_chunks == 80


def test_settings_from_env_reads_evidence_source_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    monkeypatch.setenv("PRIMARY_MODEL", "primary")
    monkeypatch.setenv("AUDIT_MODEL", "audit")
    monkeypatch.setenv("RANKING_MODEL", "ranking")
    monkeypatch.setenv("DATABASE_URL", "postgresql://shared")
    monkeypatch.setenv("PROMPTS_DIR", str(prompts_dir))
    monkeypatch.setenv("EVIDENCE_SOURCE_MODE", "summary_then_ocr_on_negative")

    settings = Settings.from_env(env_file="missing.env")

    assert settings.evidence_source_mode == "summary_then_ocr_on_negative"


def test_settings_from_env_validates_ocr_chunk_overlap_less_than_max(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    monkeypatch.setenv("PRIMARY_MODEL", "primary")
    monkeypatch.setenv("AUDIT_MODEL", "audit")
    monkeypatch.setenv("RANKING_MODEL", "ranking")
    monkeypatch.setenv("DATABASE_URL", "postgresql://shared")
    monkeypatch.setenv("PROMPTS_DIR", str(prompts_dir))
    monkeypatch.setenv("OCR_CHUNK_MAX_CHARS", "1000")
    monkeypatch.setenv("OCR_CHUNK_OVERLAP_CHARS", "1000")

    with pytest.raises(ConfigurationError, match="OCR_CHUNK_OVERLAP_CHARS must be less than OCR_CHUNK_MAX_CHARS"):
        Settings.from_env(env_file="missing.env")


def test_settings_from_env_validates_confirming_relation_text_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    monkeypatch.setenv("PRIMARY_MODEL", "primary")
    monkeypatch.setenv("AUDIT_MODEL", "audit")
    monkeypatch.setenv("RANKING_MODEL", "ranking")
    monkeypatch.setenv("DATABASE_URL", "postgresql://shared")
    monkeypatch.setenv("PROMPTS_DIR", str(prompts_dir))
    monkeypatch.setenv("CONFIRMING_RELATION_MAX_TEXT_CHARS", "0")

    with pytest.raises(ConfigurationError, match="CONFIRMING_RELATION_MAX_TEXT_CHARS must be positive"):
        Settings.from_env(env_file="missing.env")


def test_settings_from_env_validates_evidence_source_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    monkeypatch.setenv("PRIMARY_MODEL", "primary")
    monkeypatch.setenv("AUDIT_MODEL", "audit")
    monkeypatch.setenv("RANKING_MODEL", "ranking")
    monkeypatch.setenv("DATABASE_URL", "postgresql://shared")
    monkeypatch.setenv("PROMPTS_DIR", str(prompts_dir))
    monkeypatch.setenv("EVIDENCE_SOURCE_MODE", "summary_then_magic")

    with pytest.raises(ConfigurationError, match="EVIDENCE_SOURCE_MODE must be one of"):
        Settings.from_env(env_file="missing.env")
