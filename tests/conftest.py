from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def create_prompt_assets(prompts_dir: Path) -> None:
    for name in (
        "event_fact_summary.md",
        "phr_fact_summary.md",
        "logic_audit.md",
        "event_type_resolution.md",
    ):
        (prompts_dir / name).write_text("prompt", encoding="utf-8")
