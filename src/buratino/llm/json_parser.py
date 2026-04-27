"""Strict JSON parsing for LLM outputs."""

from __future__ import annotations

import json
from typing import Any

from buratino.models.contracts import AuditResult, DocumentFactResult, DocumentPhrResult
from buratino.models.errors import LlmOutputError

VERDICTS = {"подтверждено", "не подтверждено"}
PHR_VERDICTS = {"подтверждено", "не подтверждено", "не указано"}
EVENT_TYPES = {"qualitative", "quantitative"}
EVENT_COMPARISONS = {"meets_target", "below_target", "not_applicable", "insufficient_data"}
PHR_COMPARISONS = {"meets_target", "below_target", "insufficient_data"}


def parse_event_document_result(raw_text: str) -> DocumentFactResult:
    data = _parse_json_object(raw_text, required_keys={
        "document_id",
        "file_name",
        "fact_status",
        "reasoning",
        "matched_action",
        "matched_subject",
        "completion_signal",
        "observed_value",
        "observed_unit",
        "comparison_result",
        "evidence_quote",
    })
    _require_choice(data["fact_status"], VERDICTS, "fact_status")
    _require_choice(data["comparison_result"], EVENT_COMPARISONS, "comparison_result")
    return DocumentFactResult(
        document_id=_string_or_none(data["document_id"]),
        file_name=_require_string(data["file_name"], "file_name"),
        fact_status=data["fact_status"],
        reasoning=_require_string(data["reasoning"], "reasoning"),
        matched_action=_string_or_none(data["matched_action"]),
        matched_subject=_string_or_none(data["matched_subject"]),
        completion_signal=_string_or_none(data["completion_signal"]),
        observed_value=_scalar_or_none(data["observed_value"], "observed_value"),
        observed_unit=_string_or_none(data["observed_unit"]),
        comparison_result=data["comparison_result"],
        evidence_quote=_string_or_none(data["evidence_quote"]),
    )


def parse_phr_document_result(raw_text: str) -> DocumentPhrResult:
    data = _parse_json_object(raw_text, required_keys={
        "document_id",
        "file_name",
        "phr_fact_status",
        "reasoning",
        "metric_matched",
        "characteristic_explicitly_matched",
        "quantity_refers_to_metric_object",
        "observed_value",
        "observed_unit",
        "comparison_result",
        "evidence_quote",
    })
    _require_choice(data["phr_fact_status"], VERDICTS, "phr_fact_status")
    _require_choice(data["comparison_result"], PHR_COMPARISONS, "comparison_result")
    _require_bool(data["characteristic_explicitly_matched"], "characteristic_explicitly_matched")
    _require_bool(data["quantity_refers_to_metric_object"], "quantity_refers_to_metric_object")
    return DocumentPhrResult(
        document_id=_string_or_none(data["document_id"]),
        file_name=_require_string(data["file_name"], "file_name"),
        phr_fact_status=data["phr_fact_status"],
        reasoning=_require_string(data["reasoning"], "reasoning"),
        metric_matched=_string_or_none(data["metric_matched"]),
        characteristic_explicitly_matched=data["characteristic_explicitly_matched"],
        quantity_refers_to_metric_object=data["quantity_refers_to_metric_object"],
        observed_value=_scalar_or_none(data["observed_value"], "observed_value"),
        observed_unit=_string_or_none(data["observed_unit"]),
        comparison_result=data["comparison_result"],
        evidence_quote=_string_or_none(data["evidence_quote"]),
    )


def parse_audit_result(raw_text: str) -> AuditResult:
    data = _parse_json_object(raw_text, required_keys={
        "logic_is_valid",
        "detected_errors",
        "corrected_event_status",
        "corrected_phr_status",
        "corrected_reasoning",
    })
    _require_choice(data["corrected_event_status"], VERDICTS, "corrected_event_status")
    _require_choice(data["corrected_phr_status"], PHR_VERDICTS, "corrected_phr_status")
    if not isinstance(data["logic_is_valid"], bool):
        raise LlmOutputError("logic_is_valid must be boolean.")
    if not isinstance(data["detected_errors"], list) or not all(
        isinstance(item, str) for item in data["detected_errors"]
    ):
        raise LlmOutputError("detected_errors must be a list of strings.")
    return AuditResult(
        logic_is_valid=data["logic_is_valid"],
        detected_errors=data["detected_errors"],
        corrected_event_status=data["corrected_event_status"],
        corrected_phr_status=data["corrected_phr_status"],
        corrected_reasoning=_require_string(data["corrected_reasoning"], "corrected_reasoning"),
    )


def parse_event_type_result(raw_text: str) -> tuple[str, str]:
    data = _parse_json_object(raw_text, required_keys={"event_type", "reasoning"})
    _require_choice(data["event_type"], EVENT_TYPES, "event_type")
    return data["event_type"], _require_string(data["reasoning"], "reasoning")


def _parse_json_object(raw_text: str, required_keys: set[str]) -> dict[str, Any]:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise LlmOutputError(f"Malformed JSON from LLM: {exc}") from exc

    if not isinstance(payload, dict):
        raise LlmOutputError("LLM output must be a JSON object.")

    actual_keys = set(payload.keys())
    if actual_keys != required_keys:
        missing = sorted(required_keys - actual_keys)
        extra = sorted(actual_keys - required_keys)
        parts: list[str] = []
        if missing:
            parts.append(f"missing keys: {', '.join(missing)}")
        if extra:
            parts.append(f"extra keys: {', '.join(extra)}")
        raise LlmOutputError("LLM JSON schema mismatch: " + "; ".join(parts))

    return payload


def _require_choice(value: Any, allowed: set[str], field_name: str) -> None:
    if value not in allowed:
        raise LlmOutputError(f"{field_name} must be one of: {', '.join(sorted(allowed))}")


def _require_bool(value: Any, field_name: str) -> None:
    if not isinstance(value, bool):
        raise LlmOutputError(f"{field_name} must be boolean.")


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LlmOutputError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise LlmOutputError("Expected string or null.")
    stripped = value.strip()
    return stripped or None


def _scalar_or_none(value: Any, field_name: str) -> float | str | None:
    if value is None:
        return None
    if isinstance(value, (int, float, str)):
        return value
    raise LlmOutputError(f"{field_name} must be number, string, or null.")
