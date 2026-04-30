from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from buratino.cli.main import build_parser, parse_verify_command, read_event_ids, run, validate_event_id
from buratino.models.contracts import VerificationReport
from conftest import create_prompt_assets


def clear_env(monkeypatch) -> None:
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
        "CONFIRMING_RELATION_MAX_TEXT_CHARS",
    ):
        monkeypatch.delenv(key, raising=False)


@dataclass
class FakeArtifacts:
    report: VerificationReport
    json_path: Path
    xlsx_path: Path | None


class FakeApp:
    def verify(
        self,
        *,
        event_id: int,
        output_dir: Path,
        primary_model: str,
        audit_model: str,
        export_xlsx: bool,
        max_documents_to_analyze: int | None = None,
    ) -> FakeArtifacts:
        json_path = output_dir / f"event_{event_id}.json"
        json_path.write_text("{}", encoding="utf-8")
        xlsx_path = output_dir / f"event_{event_id}.xlsx" if export_xlsx else None
        return FakeArtifacts(
            report=VerificationReport(
                event_id=event_id,
                event_name="test",
                event_type="qualitative",
                event_fact_status="не подтверждено",
                phr_fact_status="не подтверждено",
                event_primary_file=None,
                phr_primary_file=None,
                logic_is_valid=True,
                primary_model=primary_model,
                audit_model=audit_model,
                event_reasoning="none",
                phr_reasoning="none",
            ),
            json_path=json_path,
            xlsx_path=xlsx_path,
        )


def test_validate_event_id_requires_integer() -> None:
    try:
        validate_event_id("abc")
    except ValueError as exc:
        assert str(exc) == "event_id must be an integer."
    else:
        raise AssertionError("Expected ValueError for non-integer event_id")


def test_validate_event_id_requires_positive_integer() -> None:
    try:
        validate_event_id("0")
    except ValueError as exc:
        assert str(exc) == "event_id must be a positive integer."
    else:
        raise AssertionError("Expected ValueError for non-positive event_id")


def test_run_verify_returns_error_when_config_is_missing(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    clear_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    exit_code = run(["verify", "123"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "PRIMARY_MODEL" in captured.err


def test_run_verify_accepts_valid_input(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    clear_env(monkeypatch)
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    monkeypatch.setenv("PRIMARY_MODEL", "primary")
    monkeypatch.setenv("AUDIT_MODEL", "audit")
    monkeypatch.setenv("MAIN_DATABASE_URL", "postgresql://main")
    monkeypatch.setenv("RUNTIME_DATABASE_URL", "postgresql://runtime")
    monkeypatch.setenv("PROMPTS_DIR", str(prompts_dir))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr("buratino.cli.main.build_app", lambda settings: FakeApp())

    exit_code = run(["verify", "123", "--xlsx"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "event_123.json" in captured.out
    assert "event_123.xlsx" in captured.out


def test_parse_verify_command_uses_validated_event_id(tmp_path: Path) -> None:
    parser = build_parser()
    args = parser.parse_args(["verify", "77", "--output-dir", str(tmp_path), "--xlsx"])

    command = parse_verify_command(args)

    assert command.event_id == 77
    assert command.output_dir == tmp_path
    assert command.export_xlsx is True


def test_read_event_ids_ignores_empty_lines_and_comments(tmp_path: Path) -> None:
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("123\n\n# comment\n456\n", encoding="utf-8")

    assert read_event_ids(ids_file) == [123, 456]


def test_run_verify_list_writes_batch_xlsx(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    clear_env(monkeypatch)
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("123\n456\n", encoding="utf-8")
    xlsx_path = tmp_path / "batch.xlsx"

    monkeypatch.setenv("PRIMARY_MODEL", "primary")
    monkeypatch.setenv("AUDIT_MODEL", "audit")
    monkeypatch.setenv("MAIN_DATABASE_URL", "postgresql://main")
    monkeypatch.setenv("RUNTIME_DATABASE_URL", "postgresql://runtime")
    monkeypatch.setenv("PROMPTS_DIR", str(prompts_dir))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr("buratino.cli.main.build_app", lambda settings: FakeApp())

    exit_code = run(["verify-list", str(ids_file), "--xlsx", str(xlsx_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert xlsx_path.exists()
    assert "Processed ids: 2" in captured.out
    assert "Successful: 2" in captured.out
