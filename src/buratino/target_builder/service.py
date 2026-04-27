"""Target normalization and event type resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass

from buratino.llm.client import LlmClient
from buratino.llm.json_parser import parse_event_type_result
from buratino.llm.prompt_loader import PromptLoader
from buratino.models.domain import EventRecord, PhrRecord, PhrTarget, VerificationTarget
from buratino.models.errors import DataContractError, ValidationError


@dataclass
class TargetBuilder:
    prompt_loader: PromptLoader
    llm_client: LlmClient
    primary_model: str

    def build_event_target(self, event: EventRecord) -> VerificationTarget:
        event_type = self._resolve_event_type(event)
        normalized_action, normalized_subject = self._extract_action_subject(event)
        return VerificationTarget(
            event_id=event.event_id,
            event_name=event.event_name,
            event_description=event.event_description,
            event_type=event_type,
            normalized_action=normalized_action,
            normalized_subject=normalized_subject,
            planned_value=event.planned_value,
            planned_unit=event.planned_unit,
        )

    def build_phr_target(self, event: EventRecord, phr: PhrRecord) -> PhrTarget:
        if phr.phr_value_2025 is None or phr.phr_unit is None:
            raise DataContractError("PHR record must include target value and unit.")
        return PhrTarget(
            event_id=event.event_id,
            event_name=event.event_name,
            phr_name=phr.phr_name,
            phr_value_2025=phr.phr_value_2025,
            phr_unit=phr.phr_unit,
        )

    def _resolve_event_type(self, event: EventRecord) -> str:
        if event.planned_value is None:
            raise DataContractError("Event planned_value is required to determine event type.")
        if event.planned_value == 0:
            return "qualitative"
        if event.planned_value > 1:
            return "quantitative"

        prompt = self.prompt_loader.render(
            "event_type_resolution.md",
            {
                "event_id": event.event_id,
                "event_name": event.event_name,
                "event_description": event.event_description,
                "planned_value": event.planned_value,
                "planned_unit": event.planned_unit,
            },
        )
        raw_response = self.llm_client.generate_json(model=self.primary_model, prompt=prompt)
        event_type, _ = parse_event_type_result(raw_response)
        return event_type

    def _extract_action_subject(self, event: EventRecord) -> tuple[str | None, str | None]:
        event_name = re.sub(r"\s+", " ", event.event_name.strip())
        event_description = (
            re.sub(r"\s+", " ", event.event_description.strip())
            if event.event_description
            else None
        )
        if not event_name:
            raise ValidationError("Event name or description is required to build the target.")

        parts = re.split(r"[-:;,.()]", event_name, maxsplit=1)
        action = parts[0].strip() or None
        subject = parts[1].strip() if len(parts) > 1 else event_description
        return action, subject
