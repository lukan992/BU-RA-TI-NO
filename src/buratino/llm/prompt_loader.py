"""Prompt asset loading and rendering."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PromptLoader:
    prompts_dir: Path

    def load(self, prompt_name: str) -> str:
        return (self.prompts_dir / prompt_name).read_text(encoding="utf-8").strip()

    def render(self, prompt_name: str, payload: dict[str, Any]) -> str:
        template = self.load(prompt_name)
        rendered_payload = json.dumps(payload, ensure_ascii=False, indent=2)
        return f"{template}\n\n## Input payload\n{rendered_payload}\n"
