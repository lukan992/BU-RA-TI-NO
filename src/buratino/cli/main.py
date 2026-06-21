"""Command-line entrypoint."""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from buratino.bootstrap import build_analysis_service, build_app
from buratino.config.errors import ConfigurationError
from buratino.config.settings import Settings
from buratino.logging import configure_logging
from buratino.models.errors import BuratinoError
from buratino.repository.analysis_results import BuratinoEventAnalysisResultRepository
from buratino.repository.jobs import BuratinoAnalysisJobRepository
from buratino.report.batch_xlsx_exporter import BatchResult, BatchXlsxExporter
from buratino.service.integration_debug import (
    enqueue_debug_job,
    inspect_job,
    integration_preflight,
    require_debug_commands_allowed,
    sanitize_dsn,
)
from buratino.service.migrations import MigrationRunner
from buratino.service.smoke import run_smoke_check, seed_smoke_db
from buratino.worker.runner import BuratinoWorker


@dataclass(frozen=True)
class VerifyCommand:
    event_id: int
    output_dir: Path | None
    export_xlsx: bool


@dataclass(frozen=True)
class VerifyListCommand:
    ids_file: Path
    output_dir: Path | None
    xlsx_path: Path
    continue_on_error: bool


@dataclass(frozen=True)
class WorkerCommand:
    once: bool
    max_jobs: int | None


@dataclass(frozen=True)
class SeedSmokeDbCommand:
    include_fail_case: bool


@dataclass(frozen=True)
class SmokeCheckCommand:
    include_fail_case: bool


@dataclass(frozen=True)
class EnqueueDebugJobCommand:
    event_id: int
    result_value_id: int | None
    priority: int
    max_attempts: int
    correlation_id: str | None
    payload_json: str | None
    allow_debug: bool


@dataclass(frozen=True)
class InspectJobCommand:
    event_id: int
    result_value_id: int | None
    as_json: bool


@dataclass(frozen=True)
class IntegrationPreflightCommand:
    event_id: int
    result_value_id: int | None
    as_json: bool


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="buratino")
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify_parser = subparsers.add_parser(
        "verify",
        help="Verify one event_id against document summaries.",
    )
    verify_parser.add_argument("event_id", help="Target event identifier.")
    verify_parser.add_argument("--output-dir", type=Path, default=None, help="Override output directory for generated artifacts.")
    verify_parser.add_argument("--xlsx", action="store_true", help="Request XLSX export when report generation is implemented.")

    verify_list_parser = subparsers.add_parser(
        "verify-list",
        help="Verify event ids from a text file and write one summary XLSX.",
    )
    verify_list_parser.add_argument("ids_file", type=Path, help="Text file with one event id per line.")
    verify_list_parser.add_argument("--output-dir", type=Path, default=None, help="Override output directory for generated JSON artifacts.")
    verify_list_parser.add_argument("--xlsx", type=Path, default=Path("output/batch_results.xlsx"), help="Output path for the batch XLSX summary.")
    verify_list_parser.add_argument("--stop-on-error", action="store_true", help="Stop batch processing after the first failed id.")

    worker_parser = subparsers.add_parser("worker", help="Run buratino pipeline worker.")
    worker_limit_group = worker_parser.add_mutually_exclusive_group()
    worker_limit_group.add_argument("--once", action="store_true", help="Claim at most one job and exit. Exit 0 if no eligible job exists.")
    worker_limit_group.add_argument("--max-jobs", type=int, default=None, help="Process up to N jobs and then exit.")

    subparsers.add_parser("migrate", help="Apply runtime SQL migrations.")

    seed_parser = subparsers.add_parser("seed-smoke-db", help="Seed a local smoke-test database for the worker flow.")
    seed_parser.add_argument("--include-fail-case", action="store_true", help="Also seed one job that must end in failed state.")

    smoke_check_parser = subparsers.add_parser("smoke-check", help="Validate local smoke-test results in PostgreSQL.")
    smoke_check_parser.add_argument("--include-fail-case", action="store_true", help="Validate the optional failed-job smoke case as well.")

    enqueue_parser = subparsers.add_parser("enqueue-debug-job", help="Create one debug pending job for manual integration testing.")
    enqueue_parser.add_argument("--event-id", required=True)
    enqueue_parser.add_argument("--result-value-id", default=None)
    enqueue_parser.add_argument("--priority", type=int, default=100)
    enqueue_parser.add_argument("--max-attempts", type=int, default=1)
    enqueue_parser.add_argument("--correlation-id", default=None)
    enqueue_parser.add_argument("--payload-json", default=None)
    enqueue_parser.add_argument("--allow-debug", action="store_true")

    inspect_parser = subparsers.add_parser("inspect-job", help="Inspect latest job/result for one event.")
    inspect_parser.add_argument("--event-id", required=True)
    inspect_parser.add_argument("--result-value-id", default=None)
    inspect_parser.add_argument("--json", action="store_true")

    preflight_parser = subparsers.add_parser("integration-preflight", help="Read-only preflight against an existing OCR database.")
    preflight_parser.add_argument("--event-id", required=True)
    preflight_parser.add_argument("--result-value-id", default=None)
    preflight_parser.add_argument("--json", action="store_true")
    return parser


def validate_event_id(raw_value: str) -> int:
    try:
        event_id = int(raw_value)
    except ValueError as exc:
        raise ValueError("event_id must be an integer.") from exc
    if event_id <= 0:
        raise ValueError("event_id must be a positive integer.")
    return event_id


def parse_verify_command(args: argparse.Namespace) -> VerifyCommand:
    return VerifyCommand(event_id=validate_event_id(args.event_id), output_dir=args.output_dir, export_xlsx=args.xlsx)


def parse_verify_list_command(args: argparse.Namespace) -> VerifyListCommand:
    return VerifyListCommand(ids_file=args.ids_file, output_dir=args.output_dir, xlsx_path=args.xlsx, continue_on_error=not args.stop_on_error)


def parse_worker_command(args: argparse.Namespace) -> WorkerCommand:
    if args.max_jobs is not None and args.max_jobs <= 0:
        raise ValueError("--max-jobs must be a positive integer.")
    return WorkerCommand(once=bool(args.once), max_jobs=args.max_jobs)


def parse_seed_smoke_db_command(args: argparse.Namespace) -> SeedSmokeDbCommand:
    return SeedSmokeDbCommand(include_fail_case=bool(args.include_fail_case))


def parse_smoke_check_command(args: argparse.Namespace) -> SmokeCheckCommand:
    return SmokeCheckCommand(include_fail_case=bool(args.include_fail_case))


def parse_enqueue_debug_job_command(args: argparse.Namespace) -> EnqueueDebugJobCommand:
    if args.priority < 0:
        raise ValueError("--priority must be >= 0.")
    if args.max_attempts <= 0:
        raise ValueError("--max-attempts must be a positive integer.")
    return EnqueueDebugJobCommand(
        event_id=validate_event_id(args.event_id),
        result_value_id=_parse_optional_positive_int(args.result_value_id),
        priority=args.priority,
        max_attempts=args.max_attempts,
        correlation_id=args.correlation_id,
        payload_json=args.payload_json,
        allow_debug=bool(args.allow_debug),
    )


def parse_inspect_job_command(args: argparse.Namespace) -> InspectJobCommand:
    return InspectJobCommand(
        event_id=validate_event_id(args.event_id),
        result_value_id=_parse_optional_positive_int(args.result_value_id),
        as_json=bool(args.json),
    )


def parse_integration_preflight_command(args: argparse.Namespace) -> IntegrationPreflightCommand:
    return IntegrationPreflightCommand(
        event_id=validate_event_id(args.event_id),
        result_value_id=_parse_optional_positive_int(args.result_value_id),
        as_json=bool(args.json),
    )


def read_event_ids(ids_file: Path) -> list[int]:
    event_ids: list[int] = []
    for line_number, raw_line in enumerate(ids_file.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            event_ids.append(validate_event_id(line))
        except ValueError as exc:
            raise ValueError(f"{ids_file}:{line_number}: {exc}") from exc
    if not event_ids:
        raise ValueError(f"No event ids found in {ids_file}")
    return event_ids


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "migrate":
            dsn = _runtime_database_dsn()
            applied = MigrationRunner(dsn=dsn, migrations_dir=Path("migrations")).run()
            print(f"Applied migrations: {len(applied)}")
            for name in applied:
                print(name)
            return 0

        if args.command == "seed-smoke-db":
            command = parse_seed_smoke_db_command(args)
            dsn = _runtime_database_dsn()
            seeded = seed_smoke_db(dsn=dsn, include_fail_case=command.include_fail_case)
            print(f"Seeded smoke events: {', '.join(str(item) for item in seeded.seeded_event_ids)}")
            print(f"Seeded jobs: {seeded.seeded_job_ids}")
            return 0

        if args.command == "smoke-check":
            command = parse_smoke_check_command(args)
            dsn = _runtime_database_dsn()
            checked = run_smoke_check(dsn=dsn, include_fail_case=command.include_fail_case)
            print(f"Smoke check passed for events: {', '.join(str(item) for item in checked.completed_events)}")
            print(f"Checked result rows: {checked.checked_results}")
            return 0

        settings = Settings.from_env()

        if args.command == "integration-preflight":
            command = parse_integration_preflight_command(args)
            configure_logging(settings.log_level)
            result = integration_preflight(
                dsn=settings.runtime_database_url,
                schema=settings.runtime_db_schema,
                event_id=command.event_id,
                result_value_id=command.result_value_id,
                summary_verdict_enabled=settings.summary_verdict_enabled,
                date_check_enabled=settings.date_check_enabled,
                audit_enabled=settings.audit_enabled,
                ranking_enabled=settings.ranking_enabled,
                debug=settings.log_level == "DEBUG",
            )
            _print_payload(result.to_dict(), as_json=command.as_json)
            return 0

        if args.command == "enqueue-debug-job":
            command = parse_enqueue_debug_job_command(args)
            require_debug_commands_allowed(
                env_allowed=settings.allow_integration_debug_commands,
                cli_allowed=command.allow_debug,
            )
            result = enqueue_debug_job(
                repository=BuratinoAnalysisJobRepository(settings.runtime_database_url),
                event_id=command.event_id,
                result_value_id=command.result_value_id,
                priority=command.priority,
                max_attempts=command.max_attempts,
                correlation_id=command.correlation_id,
                payload_json=command.payload_json,
            )
            print("DEBUG ONLY: production jobs must be created by external orchestrator.")
            _print_payload(result.to_dict(), as_json=False)
            return 0

        if args.command == "inspect-job":
            command = parse_inspect_job_command(args)
            result = inspect_job(
                job_repository=BuratinoAnalysisJobRepository(settings.runtime_database_url),
                result_repository=BuratinoEventAnalysisResultRepository(settings.runtime_database_url),
                event_id=command.event_id,
                result_value_id=command.result_value_id,
            )
            _print_payload(result.to_dict(), as_json=command.as_json)
            return 0

        if args.command == "verify":
            command = parse_verify_command(args)
            output_dir = command.output_dir or settings.output_dir
            output_dir.mkdir(parents=True, exist_ok=True)
            configure_logging(settings.log_level, log_file=output_dir / "buratino.log")
            from loguru import logger

            logger.info("Starting verification: event_id={} primary_model={}", command.event_id, settings.primary_model)
            app = build_app(settings)
            artifacts = app.verify(
                event_id=command.event_id,
                output_dir=output_dir,
                primary_model=settings.primary_model,
                audit_model=settings.audit_model,
                export_xlsx=command.export_xlsx,
                max_documents_to_analyze=settings.max_documents_to_analyze,
            )
            print(f"Verification report written to {artifacts.json_path}")
            if artifacts.xlsx_path is not None:
                print(f"XLSX report written to {artifacts.xlsx_path}")
            return 0

        if args.command == "verify-list":
            command = parse_verify_list_command(args)
            event_ids = read_event_ids(command.ids_file)
            output_dir = command.output_dir or settings.output_dir
            output_dir.mkdir(parents=True, exist_ok=True)
            configure_logging(settings.log_level, log_file=output_dir / "buratino.log")
            from loguru import logger

            results_by_index: dict[int, BatchResult] = {}
            logger.info("Starting batch verification: count={} primary_model={}", len(event_ids), settings.primary_model)
            logger.info("EVENT_MAX_CONCURRENCY={}", settings.event_max_concurrency)
            logger.info(
                "Effective max concurrent event pipelines={}, effective max concurrent LLM requests~={}",
                settings.event_max_concurrency,
                settings.event_max_concurrency,
            )
            with ThreadPoolExecutor(max_workers=settings.event_max_concurrency) as executor:
                future_to_item = {
                    executor.submit(_run_batch_item, settings, output_dir, event_id, index, len(event_ids)): (index, event_id)
                    for index, event_id in enumerate(event_ids, start=1)
                }
                for future in as_completed(future_to_item):
                    index, event_id = future_to_item[future]
                    try:
                        completed_index, result = future.result()
                    except Exception as exc:  # pragma: no cover
                        logger.error("Batch item crashed: event_id={} error={}", event_id, exc)
                        completed_index = index
                        result = BatchResult(input_event_id=event_id, status="error", error=str(exc))
                    results_by_index[completed_index] = result

            results = [results_by_index[index] for index in range(1, len(event_ids) + 1) if index in results_by_index]
            batch_path = BatchXlsxExporter(command.xlsx_path).export(results)
            print(f"Batch XLSX report written to {batch_path}")
            print(f"Processed ids: {len(results)}")
            print(f"Successful: {sum(1 for item in results if item.status == 'ok')}")
            print(f"Failed: {sum(1 for item in results if item.status == 'error')}")
            return 0

        if args.command == "worker":
            command = parse_worker_command(args)
            configure_logging(settings.log_level, log_file=settings.output_dir / "buratino.log")
            if settings.worker_max_concurrency != 1:
                raise ConfigurationError("BURATINO_MAX_CONCURRENCY > 1 is not supported in this version.")
            from loguru import logger

            logger.info(
                "worker startup worker_id={} database_url={} EVIDENCE_SOURCE_MODE={} SUMMARY_VERDICT_ENABLED={} DATE_CHECK_ENABLED={} AUDIT_ENABLED={} RANKING_ENABLED={} PRIMARY_MODEL={} LLM_BACKEND={} poll_interval={} lease_seconds={} max_concurrency={} max_jobs={} once={}",
                settings.worker_id,
                sanitize_dsn(settings.runtime_database_url),
                settings.evidence_source_mode,
                settings.summary_verdict_enabled,
                settings.date_check_enabled,
                settings.audit_enabled,
                settings.ranking_enabled,
                settings.primary_model,
                settings.llm_backend,
                settings.worker_poll_interval_seconds,
                settings.job_lease_seconds,
                settings.worker_max_concurrency,
                command.max_jobs,
                command.once,
            )
            worker = BuratinoWorker(
                analysis_service=build_analysis_service(settings),
                job_repository=BuratinoAnalysisJobRepository(settings.runtime_database_url),
                result_repository=BuratinoEventAnalysisResultRepository(settings.runtime_database_url),
                worker_id=settings.worker_id,
                poll_interval_seconds=settings.worker_poll_interval_seconds,
                lease_seconds=settings.job_lease_seconds,
                heartbeat_seconds=settings.job_heartbeat_seconds,
                dsn=settings.runtime_database_url,
            )
            processed = worker.run(once=command.once, max_jobs=command.max_jobs)
            print(f"Processed jobs: {processed}")
            return 0

        parser.error(f"Unsupported command: {args.command}")
    except (ConfigurationError, ValueError, BuratinoError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 2


def main() -> None:
    raise SystemExit(run())


def _run_batch_item(settings: Settings, output_dir: Path, event_id: int, index: int, total: int) -> tuple[int, BatchResult]:
    from loguru import logger

    started_at = time.perf_counter()
    logger.info("Batch item start: {}/{} event_id={} primary_model={}", index, total, event_id, settings.primary_model)
    try:
        app = build_app(settings)
        artifacts = app.verify(
            event_id=event_id,
            output_dir=output_dir,
            primary_model=settings.primary_model,
            audit_model=settings.audit_model,
            export_xlsx=False,
            max_documents_to_analyze=settings.max_documents_to_analyze,
        )
        duration = time.perf_counter() - started_at
        logger.info("Batch item completed: event_id={} duration_seconds={:.2f} json_path={}", event_id, duration, artifacts.json_path)
        return (
            index,
            BatchResult(
                input_event_id=event_id,
                status="ok",
                result_json=getattr(artifacts, "result_json", getattr(artifacts, "report", None)),
                json_path=artifacts.json_path,
            ),
        )
    except (BuratinoError, ValueError, ConfigurationError) as item_exc:
        duration = time.perf_counter() - started_at
        logger.error("Batch item failed: event_id={} duration_seconds={:.2f} error={}", event_id, duration, item_exc)
        return index, BatchResult(input_event_id=event_id, status="error", error=str(item_exc))


def _runtime_database_dsn() -> str:
    import os

    return os.getenv("RUNTIME_DATABASE_URL") or os.getenv("DATABASE_URL") or os.getenv("MAIN_DATABASE_URL") or _raise_missing_runtime_dsn()


def _raise_missing_runtime_dsn() -> str:
    raise ConfigurationError("Missing required environment variable: RUNTIME_DATABASE_URL (or fallback DATABASE_URL).")


def _parse_optional_positive_int(raw_value: str | None) -> int | None:
    if raw_value is None:
        return None
    return validate_event_id(raw_value)


def _print_payload(payload: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")
