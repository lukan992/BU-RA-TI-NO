from __future__ import annotations

from pathlib import Path

import pytest

from buratino.config.errors import ConfigurationError
from buratino.config.settings import Settings
from conftest import create_prompt_assets


@pytest.fixture(autouse=True)
def clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
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
        "MAX_DOCUMENTS_TO_ANALYZE",
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
    assert settings.output_dir == Path("custom-output")
    assert settings.llm_timeout_seconds == 120.0
    assert settings.llm_temperature == 0.0
    assert settings.llm_max_tokens is None
    assert settings.max_documents_to_analyze is None


def test_settings_from_env_validates_temperature_range(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    monkeypatch.setenv("PRIMARY_MODEL", "primary")
    monkeypatch.setenv("AUDIT_MODEL", "audit")
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
    monkeypatch.setenv("DATABASE_URL", "postgresql://shared")
    monkeypatch.setenv("PROMPTS_DIR", str(prompts_dir))
    monkeypatch.setenv("MAX_DOCUMENTS_TO_ANALYZE", "10")

    settings = Settings.from_env(env_file="missing.env")

    assert settings.max_documents_to_analyze == 10
