"""Derived XLSX export for the independent buratino result."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from openpyxl import Workbook


@dataclass(frozen=True)
class BuratinoXlsxExporter:
    output_path: Path

    def export(self, result_json: dict) -> Path:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "result"
        sheet.append(["field", "value"])

        statuses = result_json["statuses"]
        expected = result_json["expected"]
        facts = result_json["facts"]
        diagnostics = result_json["diagnostics"]

        rows = [
            ("ID мероприятия", result_json["event_id"]),
            ("Наименование мероприятия", result_json["event_name"]),
            ("Статус пункта: Описание мероприятия", statuses["event_description_status"]),
            ("Описание мероприятия", expected["event_description"]),
            ("Описание мероприятия, факт", facts["event_description_fact"]),
            ("Статус пункта: ПХР", statuses["phr_status"]),
            ("ПХР", expected["phr"]),
            ("ПХР, факт", facts["phr_fact"]),
            ("Статус пункта: План", statuses["plan_status"]),
            ("План", expected["plan"]),
            ("План, факт", facts["plan_fact"]),
            (
                "supporting_files",
                ", ".join(item["filename"] for item in result_json["supporting_files"]),
            ),
            ("diagnostic_reason", diagnostics["diagnostic_reason"]),
        ]
        for key, value in rows:
            sheet.append([key, value])

        workbook.save(self.output_path)
        return self.output_path
