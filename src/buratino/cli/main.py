"""Command-line entrypoint."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from buratino.bootstrap import build_app
from buratino.config.errors import ConfigurationError
from buratino.config.settings import Settings
from buratino.logging import configure_logging
from buratino.models.errors import BuratinoError
from buratino.report.batch_xlsx_exporter import BatchResult, BatchXlsxExporter


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="buratino")
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify_parser = subparsers.add_parser(
        "verify",
        help="Verify one event_id against document summaries.",
    )
    verify_parser.add_argument("event_id", help="Target event identifier.")
    verify_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Override output directory for generated artifacts.",
    )
    verify_parser.add_argument(
        "--xlsx",
        action="store_true",
        help="Request XLSX export when report generation is implemented.",
    )

    verify_list_parser = subparsers.add_parser(
        "verify-list",
        help="Verify event ids from a text file and write one summary XLSX.",
    )
    verify_list_parser.add_argument("ids_file", type=Path, help="Text file with one event id per line.")
    verify_list_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Override output directory for generated JSON artifacts.",
    )
    verify_list_parser.add_argument(
        "--xlsx",
        type=Path,
        default=Path("output/batch_results.xlsx"),
        help="Output path for the batch XLSX summary.",
    )
    verify_list_parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop batch processing after the first failed id.",
    )
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
    return VerifyCommand(
        event_id=validate_event_id(args.event_id),
        output_dir=args.output_dir,
        export_xlsx=args.xlsx,
    )


def parse_verify_list_command(args: argparse.Namespace) -> VerifyListCommand:
    return VerifyListCommand(
        ids_file=args.ids_file,
        output_dir=args.output_dir,
        xlsx_path=args.xlsx,
        continue_on_error=not args.stop_on_error,
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
        settings = Settings.from_env()
        configure_logging(settings.log_level)
        from loguru import logger

        if args.command == "verify":
            command = parse_verify_command(args)
            logger.info("Starting verification: event_id={}", command.event_id)
            app = build_app(settings)
            output_dir = command.output_dir or settings.output_dir
            output_dir.mkdir(parents=True, exist_ok=True)
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
            app = build_app(settings)
            results: list[BatchResult] = []
            logger.info("Starting batch verification: count={}", len(event_ids))
            for index, event_id in enumerate(event_ids, start=1):
                logger.info("Batch item {}/{}: event_id={}", index, len(event_ids), event_id)
                try:
                    artifacts = app.verify(
                        event_id=event_id,
                        output_dir=output_dir,
                        primary_model=settings.primary_model,
                        audit_model=settings.audit_model,
                        export_xlsx=False,
                        max_documents_to_analyze=settings.max_documents_to_analyze,
                    )
                    results.append(
                        BatchResult(
                            input_event_id=event_id,
                            status="ok",
                            report=artifacts.report,
                            json_path=artifacts.json_path,
                        )
                    )
                except (BuratinoError, ValueError, ConfigurationError) as item_exc:
                    logger.error("Batch item failed: event_id={} error={}", event_id, item_exc)
                    results.append(
                        BatchResult(
                            input_event_id=event_id,
                            status="error",
                            error=str(item_exc),
                        )
                    )
                    if not command.continue_on_error:
                        break
            batch_path = BatchXlsxExporter(command.xlsx_path).export(results)
            print(f"Batch XLSX report written to {batch_path}")
            print(f"Processed ids: {len(results)}")
            print(f"Successful: {sum(1 for item in results if item.status == 'ok')}")
            print(f"Failed: {sum(1 for item in results if item.status == 'error')}")
            return 0

        parser.error(f"Unsupported command: {args.command}")
    except (ConfigurationError, ValueError, BuratinoError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 2


def main() -> None:
    raise SystemExit(run())
