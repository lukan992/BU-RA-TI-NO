"""JSON report writer."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from buratino.models.contracts import VerificationReport


@dataclass(frozen=True)
class JsonReportWriter:
    output_dir: Path

    def write(self, report: VerificationReport) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        target_path = self.output_dir / f"event_{report.event_id}.json"
        target_path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return target_path
