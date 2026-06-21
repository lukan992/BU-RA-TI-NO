"""CLI adapter around the independent buratino analysis service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from buratino.report.buratino_xlsx_exporter import BuratinoXlsxExporter
from buratino.report.json_writer import JsonReportWriter
from buratino.service.analysis import BuratinoAnalysisService


@dataclass(frozen=True)
class VerificationArtifacts:
    result_json: dict
    json_path: Path
    xlsx_path: Path | None


@dataclass
class VerificationApp:
    analysis_service: BuratinoAnalysisService

    def verify(
        self,
        *,
        event_id: int,
        output_dir: Path,
        primary_model: str,
        audit_model: str,
        export_xlsx: bool,
        max_documents_to_analyze: int | None = None,
    ) -> VerificationArtifacts:
        del primary_model
        del audit_model
        del max_documents_to_analyze

        logger.info("Starting OCR-only buratino analysis")
        result_json = self.analysis_service.analyze_event(event_id)

        json_writer = JsonReportWriter(output_dir)
        json_path = json_writer.write(result_json, event_id=event_id)
        result_json["json_path"] = str(json_path)
        json_path = json_writer.write(result_json, event_id=event_id)

        xlsx_path: Path | None = None
        if export_xlsx:
            target_path = output_dir / f"event_{event_id}.xlsx"
            xlsx_path = BuratinoXlsxExporter(target_path).export(result_json)

        logger.info("Verification completed")
        return VerificationArtifacts(
            result_json=result_json,
            json_path=json_path,
            xlsx_path=xlsx_path,
        )
