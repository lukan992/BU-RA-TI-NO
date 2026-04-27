"""Batch XLSX export."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from openpyxl import Workbook

from buratino.models.contracts import VerificationReport


@dataclass(frozen=True)
class BatchResult:
    input_event_id: int
    status: str
    report: VerificationReport | None = None
    json_path: Path | None = None
    error: str | None = None


@dataclass(frozen=True)
class BatchXlsxExporter:
    output_path: Path

    def export(self, results: list[BatchResult]) -> Path:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "results"
        sheet.append(
            [
                "input_event_id",
                "status",
                "canonical_event_id",
                "event_name",
                "event_type",
                "event_fact_status",
                "phr_fact_status",
                "event_primary_file",
                "phr_primary_file",
                "logic_is_valid",
                "primary_model",
                "audit_model",
                "event_reasoning",
                "phr_reasoning",
                "supporting_files",
                "json_path",
                "error",
            ]
        )

        for result in results:
            report = result.report
            sheet.append(
                [
                    result.input_event_id,
                    result.status,
                    report.event_id if report is not None else None,
                    report.event_name if report is not None else None,
                    report.event_type if report is not None else None,
                    report.event_fact_status if report is not None else None,
                    report.phr_fact_status if report is not None else None,
                    report.event_primary_file if report is not None else None,
                    report.phr_primary_file if report is not None else None,
                    report.logic_is_valid if report is not None else None,
                    report.primary_model if report is not None else None,
                    report.audit_model if report is not None else None,
                    report.event_reasoning if report is not None else None,
                    report.phr_reasoning if report is not None else None,
                    ", ".join(report.supporting_files) if report is not None else None,
                    str(result.json_path) if result.json_path is not None else None,
                    result.error,
                ]
            )

        workbook.save(self.output_path)
        return self.output_path
