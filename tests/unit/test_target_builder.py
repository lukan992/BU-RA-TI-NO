from __future__ import annotations

from pathlib import Path

from buratino.llm.prompt_loader import PromptLoader
from buratino.models.domain import EventRecord
from buratino.target_builder.service import TargetBuilder
from conftest import create_prompt_assets


class FakeLlmClient:
    def __init__(self, response: str) -> None:
        self.response = response

    def generate_json(self, *, model: str, prompt: str) -> str:
        return self.response


def test_target_builder_resolves_builtin_types(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    builder = TargetBuilder(
        prompt_loader=PromptLoader(prompts_dir),
        llm_client=FakeLlmClient('{"event_type":"quantitative","reasoning":"unused"}'),
        primary_model="primary",
    )

    qualitative = builder.build_event_target(
        EventRecord(1, "Создать документ", "описание", 0, "шт")
    )
    quantitative = builder.build_event_target(
        EventRecord(2, "Построить объекты", "описание", 2, "ед")
    )

    assert qualitative.event_type == "qualitative"
    assert quantitative.event_type == "quantitative"


def test_target_builder_uses_llm_for_planned_value_one(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)

    builder = TargetBuilder(
        prompt_loader=PromptLoader(prompts_dir),
        llm_client=FakeLlmClient('{"event_type":"qualitative","reasoning":"context"}'),
        primary_model="primary",
    )

    target = builder.build_event_target(
        EventRecord(3, "Обеспечить внедрение", "по описанию без численного сравнения", 1, "ед")
    )

    assert target.event_type == "qualitative"
    assert target.normalized_action == "Обеспечить внедрение"
