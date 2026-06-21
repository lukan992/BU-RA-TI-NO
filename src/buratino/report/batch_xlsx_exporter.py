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
                "event_diagnostic_reasoning",
                "phr_diagnostic_reasoning",
                "diagnostic_stage",
                "diagnostic_reason",
                "evidence_source_used",
                "ocr_available",
                "summary_available",
                "ranking_selected_files",
                "analyzed_files",
                "doc_level_confirmed_files",
                "docs_rejected_by_empty_evidence",
                "docs_rejected_by_relation",
                "docs_rejected_by_date",
                "audit_changed_decision",
                "missing_requirements_human",
                "best_candidate_file",
                "best_candidate_reason",
                "error_stage",
                "error_type",
                "raw_response_preview",
                "model_name",
                "prompt_name",
                "total_docs",
                "ranking_enabled",
                "ranking_limit",
                "ranking_selected_doc_ids",
                "ranking_selected_file_names",
                "ranking_rejected_file_names",
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
                    report.event_diagnostic_reasoning if report is not None else None,
                    report.phr_diagnostic_reasoning if report is not None else None,
                    report.diagnostic_stage if report is not None else None,
                    report.diagnostic_reason if report is not None else None,
                    ", ".join(report.evidence_source_used) if report is not None else None,
                    report.ocr_available if report is not None else None,
                    report.summary_available if report is not None else None,
                    ", ".join(report.ranking_selected_files) if report is not None else None,
                    ", ".join(report.analyzed_files) if report is not None else None,
                    ", ".join(report.doc_level_confirmed_files) if report is not None else None,
                    ", ".join(report.docs_rejected_by_empty_evidence) if report is not None else None,
                    ", ".join(report.docs_rejected_by_relation) if report is not None else None,
                    ", ".join(report.docs_rejected_by_date) if report is not None else None,
                    report.audit_changed_decision if report is not None else None,
                    ", ".join(report.missing_requirements_human) if report is not None else None,
                    report.best_candidate_file if report is not None else None,
                    report.best_candidate_reason if report is not None else None,
                    report.error_stage if report is not None else None,
                    report.error_type if report is not None else None,
                    report.raw_response_preview if report is not None else None,
                    report.model_name if report is not None else None,
                    report.prompt_name if report is not None else None,
                    report.total_docs if report is not None else None,
                    report.ranking_enabled if report is not None else None,
                    report.ranking_limit if report is not None else None,
                    ", ".join(report.ranking_selected_doc_ids) if report is not None else None,
                    ", ".join(report.ranking_selected_file_names) if report is not None else None,
                    ", ".join(report.ranking_rejected_file_names) if report is not None else None,
                    ", ".join(report.ocr_chunks_analyzed) if report is not None else None,
                    report.event_deadline_status if report is not None else None,
                    report.event_deadline_reason if report is not None else None,
                    report.event_deadline_date if report is not None else None,
                    report.event_deadline_source_file if report is not None else None,
                    report.event_deadline_source if report is not None else None,
                    report.event_deadline_raw_text if report is not None else None,
                    report.implementation_deadline_raw if report is not None else None,
                    report.implementation_deadline_normalized if report is not None else None,
                    ", ".join(report.date_checked_files) if report is not None else None,
                    ", ".join(report.date_missing_files) if report is not None else None,
                    ", ".join(report.date_late_files) if report is not None else None,
                    ", ".join(report.date_on_time_files) if report is not None else None,
                    str(report.supporting_files_date_status) if report is not None else None,
                    ", ".join(report.supporting_files) if report is not None else None,
                    str(result.json_path) if result.json_path is not None else None,
                    result.error,
                ]
            )

        workbook.save(self.output_path)
        return self.output_path
