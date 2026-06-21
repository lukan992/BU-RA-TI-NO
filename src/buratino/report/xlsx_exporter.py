"""Derived XLSX export for the verification report."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from openpyxl import Workbook

from buratino.models.contracts import VerificationReport


@dataclass(frozen=True)
class XlsxReportExporter:
    output_dir: Path

    def export(self, report: VerificationReport) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        target_path = self.output_dir / f"event_{report.event_id}.xlsx"

        workbook = Workbook()
        summary_sheet = workbook.active
        summary_sheet.title = "summary"
        summary_sheet.append(["field", "value"])
        for key, value in report.to_dict().items():
            if isinstance(value, (dict, list)):
                summary_sheet.append([key, str(value)])
            else:
                summary_sheet.append([key, value])

        docs_sheet = workbook.create_sheet("documents")
        docs_sheet.append(
            [
                "kind",
                "file_name",
                "status",
                "reasoning",
                "evidence_quote",
                "evidence_source_used",
                "ocr_available",
                "summary_available",
                "diagnostic_stage",
                "diagnostic_reason",
                "missing_requirements_human",
                "error_stage",
                "error_type",
                "raw_response_preview",
                "model_name",
                "prompt_name",
                "ocr_chunks_analyzed",
                "event_deadline_status",
                "event_deadline_reason",
                "event_deadline_date",
                "event_deadline_source_file",
                "event_deadline_source",
                "event_deadline_raw_text",
                "implementation_deadline_raw",
                "implementation_deadline_normalized",
                "date_checked_files",
                "date_missing_files",
                "date_late_files",
                "date_on_time_files",
                "supporting_files_date_status",
            ]
        )
        for document in report.event_documents:
            docs_sheet.append(
                [
                    "event",
                    document.file_name,
                    document.fact_status,
                    document.reasoning,
                    document.evidence_quote,
                    document.evidence_source_used,
                    document.ocr_available,
                    document.summary_available,
                    document.diagnostic_stage,
                    document.diagnostic_reason,
                    ", ".join(document.missing_requirements_human),
                    document.error_stage,
                    document.error_type,
                    document.raw_response_preview,
                    document.model_name,
                    document.prompt_name,
                    ", ".join(report.ocr_chunks_analyzed),
                    report.event_deadline_status,
                    report.event_deadline_reason,
                    report.event_deadline_date,
                    report.event_deadline_source_file,
                    report.event_deadline_source,
                    report.event_deadline_raw_text,
                    report.implementation_deadline_raw,
                    report.implementation_deadline_normalized,
                    ", ".join(report.date_checked_files),
                    ", ".join(report.date_missing_files),
                    ", ".join(report.date_late_files),
                    ", ".join(report.date_on_time_files),
                    str(report.supporting_files_date_status),
                ]
            )
        for document in report.phr_documents:
            docs_sheet.append(
                [
                    "phr",
                    document.file_name,
                    document.phr_fact_status,
                    document.reasoning,
                    document.evidence_quote,
                    document.evidence_source_used,
                    document.ocr_available,
                    document.summary_available,
                    document.diagnostic_stage,
                    document.diagnostic_reason,
                    ", ".join(document.missing_requirements_human),
                    document.error_stage,
                    document.error_type,
                    document.raw_response_preview,
                    document.model_name,
                    document.prompt_name,
                    ", ".join(report.ocr_chunks_analyzed),
                    report.event_deadline_status,
                    report.event_deadline_reason,
                    report.event_deadline_date,
                    report.event_deadline_source_file,
                    report.event_deadline_source,
                    report.event_deadline_raw_text,
                    report.implementation_deadline_raw,
                    report.implementation_deadline_normalized,
                    ", ".join(report.date_checked_files),
                    ", ".join(report.date_missing_files),
                    ", ".join(report.date_late_files),
                    ", ".join(report.date_on_time_files),
                    str(report.supporting_files_date_status),
                ]
            )

        workbook.save(target_path)
        return target_path
