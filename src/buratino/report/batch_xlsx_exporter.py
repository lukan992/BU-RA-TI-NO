"""Batch XLSX export for the worker-compatible buratino contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from openpyxl import Workbook

@dataclass(frozen=True)
class BatchResult:
    input_event_id: int
    status: str
    result_json: dict | None = None
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
                "event_id",
                "event_name",
                "event_description_status",
                "phr_status",
                "plan_status",
                "event_description",
                "event_description_fact",
                "phr",
                "phr_fact",
                "plan",
                "plan_fact",
                "supporting_files",
                "diagnostic_reason",
                "ocr_available",
                "analyzed_files",
                "skipped_files",
                "json_path",
                "error",
            ]
        )

        for result in results:
            payload = _coerce_payload(result.result_json)
            sheet.append(
                [
                    result.input_event_id,
                    result.status,
                    payload["event_id"] if payload is not None else None,
                    payload["event_name"] if payload is not None else None,
                    payload["statuses"]["event_description_status"] if payload is not None else None,
                    payload["statuses"]["phr_status"] if payload is not None else None,
                    payload["statuses"]["plan_status"] if payload is not None else None,
                    payload["expected"]["event_description"] if payload is not None else None,
                    payload["facts"]["event_description_fact"] if payload is not None else None,
                    payload["expected"]["phr"] if payload is not None else None,
                    payload["facts"]["phr_fact"] if payload is not None else None,
                    payload["expected"]["plan"] if payload is not None else None,
                    payload["facts"]["plan_fact"] if payload is not None else None,
                    (
                        ", ".join(item["filename"] for item in payload["supporting_files"])
                        if payload is not None
                        else None
                    ),
                    payload["diagnostics"]["diagnostic_reason"] if payload is not None else None,
                    payload["diagnostics"]["ocr_available"] if payload is not None else None,
                    (
                        ", ".join(payload["diagnostics"]["analyzed_files"])
                        if payload is not None
                        else None
                    ),
                    (
                        ", ".join(payload["diagnostics"]["skipped_files"])
                        if payload is not None
                        else None
                    ),
                    str(result.json_path) if result.json_path is not None else None,
                    result.error,
                ]
            )

        workbook.save(self.output_path)
        return self.output_path


def _coerce_payload(payload):
    if payload is None or isinstance(payload, dict):
        return payload
    if hasattr(payload, "to_dict"):
        raw = payload.to_dict()
        return {
            "event_id": raw.get("event_id"),
            "event_name": raw.get("event_name"),
            "statuses": {
                "event_description_status": raw.get("event_fact_status"),
                "phr_status": raw.get("phr_fact_status"),
                "plan_status": None,
            },
            "expected": {
                "event_description": None,
                "phr": None,
                "plan": None,
            },
            "facts": {
                "event_description_fact": None,
                "phr_fact": None,
                "plan_fact": None,
            },
            "supporting_files": [
                {"filename": item}
                for item in raw.get("supporting_files", [])
            ],
            "diagnostics": {
                "diagnostic_reason": raw.get("diagnostic_reason"),
                "ocr_available": raw.get("ocr_available"),
                "analyzed_files": raw.get("analyzed_files", []),
                "skipped_files": [],
            },
        }
    return None
