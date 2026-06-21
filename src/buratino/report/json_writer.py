"""JSON result writer."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class JsonReportWriter:
    output_dir: Path

    def write(self, payload: dict, *, event_id: int) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        target_path = self.output_dir / f"event_{event_id}.json"
        target_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return target_path
