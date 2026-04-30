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
        docs_sheet.append(["kind", "file_name", "status", "reasoning", "evidence_quote"])
        for document in report.event_documents:
            docs_sheet.append(
                ["event", document.file_name, document.fact_status, document.reasoning, document.evidence_quote]
            )
        for document in report.phr_documents:
            docs_sheet.append(
                ["phr", document.file_name, document.phr_fact_status, document.reasoning, document.evidence_quote]
            )

        workbook.save(target_path)
        return target_path
