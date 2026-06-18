"""Strict JSON parsing for LLM outputs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from buratino.models.contracts import (
    AuditResult,
    AuditRuleViolation,
    DocumentFactResult,
    DocumentPhrResult,
    EvidenceItem,
    RankedDocument,
    ReasoningTrace,
    RelationLlmResult,
)
from buratino.models.errors import LlmOutputError

VERDICTS = {"подтверждено", "не подтверждено"}
PHR_VERDICTS = {"подтверждено", "не подтверждено", "не указано"}
EVENT_TYPES = {"qualitative", "quantitative"}
EVENT_COMPARISONS = {"meets_target", "below_target", "not_applicable", "insufficient_data"}
PHR_COMPARISONS = {"meets_target", "below_target", "insufficient_data"}
TRACE_CONFIDENCE = {"low", "medium", "high"}
RELATION_TO_EVENT = {"direct", "indirect", "none", "unclear"}
AUDIT_RESULTS = {"pass", "flip", "error"}


@dataclass(frozen=True)
class TraceLimits:
    max_items: int = 5
    short_rationale_max_chars: int = 300
    evidence_quote_max_chars: int = 500


DEFAULT_TRACE_LIMITS = TraceLimits()


def parse_event_document_result(raw_text: str, *, trace_limits: TraceLimits = DEFAULT_TRACE_LIMITS) -> DocumentFactResult:
    data = _parse_json_object(
        raw_text,
        required_keys={
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
            "reasoning_trace",
        },
    )
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
        evidence_quote=_bounded_optional_string(
            data["evidence_quote"],
            "evidence_quote",
            trace_limits.evidence_quote_max_chars,
        ),
        reasoning_trace=_parse_reasoning_trace(data["reasoning_trace"], trace_limits=trace_limits),
    )


def parse_phr_document_result(raw_text: str, *, trace_limits: TraceLimits = DEFAULT_TRACE_LIMITS) -> DocumentPhrResult:
    data = _parse_json_object(
        raw_text,
        required_keys={
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
            "reasoning_trace",
        },
    )
    _require_choice(data["phr_fact_status"], VERDICTS, "phr_fact_status")
    comparison_result = _normalize_phr_comparison_result(data["comparison_result"])
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
        comparison_result=comparison_result,
        evidence_quote=_bounded_optional_string(
            data["evidence_quote"],
            "evidence_quote",
            trace_limits.evidence_quote_max_chars,
        ),
        reasoning_trace=_parse_reasoning_trace(data["reasoning_trace"], trace_limits=trace_limits),
    )


def parse_confirming_documents_relation_result(raw_text: str) -> RelationLlmResult:
    data = _parse_json_object(raw_text, required_keys={"documents"})
    documents = data["documents"]
    if not isinstance(documents, list):
        raise LlmOutputError("documents must be a list.")

    parsed_documents: list[dict[str, str | None]] = []
    for item in documents:
        if not isinstance(item, dict):
            raise LlmOutputError("Each relation document must be a JSON object.")
        expected_keys = {"doc_id", "relation_to_event", "relation_reason"}
        actual_keys = set(item.keys())
        if actual_keys != expected_keys:
            raise LlmOutputError(_schema_mismatch_message("Relation document schema mismatch", expected_keys, actual_keys))
        _require_choice(item["relation_to_event"], RELATION_TO_EVENT, "relation_to_event")
        parsed_documents.append(
            {
                "doc_id": _string_or_none(item["doc_id"]),
                "relation_to_event": item["relation_to_event"],
                "relation_reason": _require_string(item["relation_reason"], "relation_reason"),
            }
        )
    return RelationLlmResult(documents=parsed_documents)


def parse_document_ranking_result(raw_text: str) -> list[RankedDocument]:
    data = _parse_json_object(raw_text, required_keys={"ranked_documents"})
    ranked_documents_raw = data["ranked_documents"]
    if not isinstance(ranked_documents_raw, list):
        raise LlmOutputError("ranked_documents must be a list.")

    ranked_documents: list[RankedDocument] = []
    for item in ranked_documents_raw:
        if not isinstance(item, dict):
            raise LlmOutputError("Each ranked document must be a JSON object.")
        expected_keys = {"doc_id", "score", "reason_codes", "short_reason"}
        actual_keys = set(item.keys())
        if actual_keys != expected_keys:
            raise LlmOutputError(_schema_mismatch_message("Ranking document schema mismatch", expected_keys, actual_keys))
        score = item["score"]
        if not isinstance(score, int):
            raise LlmOutputError("score must be an integer.")
        reason_codes = _require_string_list(item["reason_codes"], "reason_codes")
        short_reason = _require_string(item["short_reason"], "short_reason")
        ranked_documents.append(
            RankedDocument(
                document_id=_string_or_none(item["doc_id"]),
                file_name="",
                rank=0,
                reasoning=short_reason,
                score=score,
                reason_codes=reason_codes,
                short_reason=short_reason,
            )
        )
    return ranked_documents


def parse_audit_result(raw_text: str) -> AuditResult:
    data = _parse_json_object(
        raw_text,
        required_keys={
            "audit_result",
            "rule_violations",
            "final_event_fact_status",
            "final_phr_fact_status",
            "final_supporting_files",
        },
    )
    _require_choice(data["audit_result"], AUDIT_RESULTS, "audit_result")
    _require_choice(data["final_event_fact_status"], VERDICTS, "final_event_fact_status")
    _require_choice(data["final_phr_fact_status"], PHR_VERDICTS, "final_phr_fact_status")
    violations = _parse_audit_rule_violations(data["rule_violations"])
    final_supporting_files = _require_string_list(data["final_supporting_files"], "final_supporting_files")
    detected_errors = [violation.rule for violation in violations]
    logic_is_valid = data["audit_result"] == "pass"
    corrected_reasoning = (
        "Audit passed without rule violations."
        if logic_is_valid
        else "; ".join(violation.reason for violation in violations) or "Audit detected rule violations."
    )
    return AuditResult(
        logic_is_valid=logic_is_valid,
        detected_errors=detected_errors,
        corrected_event_status=data["final_event_fact_status"],
        corrected_phr_status=data["final_phr_fact_status"],
        corrected_reasoning=corrected_reasoning,
        audit_result=data["audit_result"],
        rule_violations=violations,
        final_supporting_files=final_supporting_files,
    )


def parse_event_type_result(raw_text: str) -> tuple[str, str]:
    data = _parse_json_object(raw_text, required_keys={"event_type", "reasoning"})
    _require_choice(data["event_type"], EVENT_TYPES, "event_type")
    return data["event_type"], _require_string(data["reasoning"], "reasoning")


def _parse_reasoning_trace(raw_value: Any, *, trace_limits: TraceLimits) -> ReasoningTrace:
    if not isinstance(raw_value, dict):
        raise LlmOutputError("reasoning_trace must be a JSON object.")
    expected_keys = {
        "reason_codes",
        "evidence_items",
        "missing_requirements",
        "short_rationale",
        "confidence",
    }
    actual_keys = set(raw_value.keys())
    if actual_keys != expected_keys:
        raise LlmOutputError(_schema_mismatch_message("Reasoning trace schema mismatch", expected_keys, actual_keys))
    _require_choice(raw_value["confidence"], TRACE_CONFIDENCE, "confidence")
    reason_codes = _require_string_list(raw_value["reason_codes"], "reason_codes", max_items=trace_limits.max_items)
    missing_requirements = _require_string_list(
        raw_value["missing_requirements"],
        "missing_requirements",
        max_items=trace_limits.max_items,
    )
    evidence_items_raw = raw_value["evidence_items"]
    if not isinstance(evidence_items_raw, list):
        raise LlmOutputError("evidence_items must be a list.")
    if len(evidence_items_raw) > trace_limits.max_items:
        raise LlmOutputError(f"evidence_items must contain at most {trace_limits.max_items} items.")
    evidence_items = [_parse_evidence_item(item, trace_limits=trace_limits) for item in evidence_items_raw]
    short_rationale = _require_string(raw_value["short_rationale"], "short_rationale")
    if len(short_rationale) > trace_limits.short_rationale_max_chars:
        raise LlmOutputError(
            f"short_rationale must be at most {trace_limits.short_rationale_max_chars} characters."
        )
    return ReasoningTrace(
        reason_codes=reason_codes,
        evidence_items=evidence_items,
        missing_requirements=missing_requirements,
        short_rationale=short_rationale,
        confidence=raw_value["confidence"],
    )


def _parse_evidence_item(raw_value: Any, *, trace_limits: TraceLimits) -> EvidenceItem:
    if not isinstance(raw_value, dict):
        raise LlmOutputError("Each evidence item must be a JSON object.")
    expected_keys = {"quote", "page", "source", "why_relevant"}
    actual_keys = set(raw_value.keys())
    if actual_keys != expected_keys:
        raise LlmOutputError(_schema_mismatch_message("Evidence item schema mismatch", expected_keys, actual_keys))
    page = raw_value["page"]
    if page is not None and not isinstance(page, int):
        raise LlmOutputError("page must be integer or null.")
    quote = _require_string(raw_value["quote"], "quote")
    if len(quote) > trace_limits.evidence_quote_max_chars:
        raise LlmOutputError(f"quote must be at most {trace_limits.evidence_quote_max_chars} characters.")
    return EvidenceItem(
        quote=quote,
        page=page,
        source=_require_string(raw_value["source"], "source"),
        why_relevant=_require_string(raw_value["why_relevant"], "why_relevant"),
    )


def _parse_audit_rule_violations(raw_value: Any) -> list[AuditRuleViolation]:
    if not isinstance(raw_value, list):
        raise LlmOutputError("rule_violations must be a list.")
    violations: list[AuditRuleViolation] = []
    for item in raw_value:
        if not isinstance(item, dict):
            raise LlmOutputError("Each rule violation must be a JSON object.")
        expected_keys = {"rule", "affected_field", "from", "to", "reason"}
        actual_keys = set(item.keys())
        if actual_keys != expected_keys:
            raise LlmOutputError(_schema_mismatch_message("Audit rule violation schema mismatch", expected_keys, actual_keys))
        violations.append(
            AuditRuleViolation(
                rule=_require_string(item["rule"], "rule"),
                affected_field=_require_string(item["affected_field"], "affected_field"),
                from_value=_require_string(item["from"], "from"),
                to_value=_require_string(item["to"], "to"),
                reason=_require_string(item["reason"], "reason"),
            )
        )
    return violations


def _parse_json_object(raw_text: str, required_keys: set[str]) -> dict[str, Any]:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise LlmOutputError(f"Malformed JSON from LLM: {exc}") from exc

    if not isinstance(payload, dict):
        raise LlmOutputError("LLM output must be a JSON object.")

    actual_keys = set(payload.keys())
    if actual_keys != required_keys:
        raise LlmOutputError(_schema_mismatch_message("LLM JSON schema mismatch", required_keys, actual_keys))

    return payload


def _schema_mismatch_message(prefix: str, expected_keys: set[str], actual_keys: set[str]) -> str:
    missing = sorted(expected_keys - actual_keys)
    extra = sorted(actual_keys - expected_keys)
    parts: list[str] = []
    if missing:
        parts.append(f"missing keys: {', '.join(missing)}")
    if extra:
        parts.append(f"extra keys: {', '.join(extra)}")
    return prefix + ": " + "; ".join(parts)


def _require_choice(value: Any, allowed: set[str], field_name: str) -> None:
    if value not in allowed:
        raise LlmOutputError(f"{field_name} must be one of: {', '.join(sorted(allowed))}")


def _normalize_phr_comparison_result(value: Any) -> str:
    if value == "not_applicable":
        return "insufficient_data"
    _require_choice(value, PHR_COMPARISONS, "comparison_result")
    return value


def _require_bool(value: Any, field_name: str) -> None:
    if not isinstance(value, bool):
        raise LlmOutputError(f"{field_name} must be boolean.")


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LlmOutputError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _require_string_list(value: Any, field_name: str, *, max_items: int | None = None) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise LlmOutputError(f"{field_name} must be a list of non-empty strings.")
    if max_items is not None and len(value) > max_items:
        raise LlmOutputError(f"{field_name} must contain at most {max_items} items.")
    return [item.strip() for item in value]


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise LlmOutputError("Expected string or null.")
    stripped = value.strip()
    return stripped or None


def _bounded_optional_string(value: Any, field_name: str, max_chars: int) -> str | None:
    rendered = _string_or_none(value)
    if rendered is not None and len(rendered) > max_chars:
        raise LlmOutputError(f"{field_name} must be at most {max_chars} characters.")
    return rendered


def _scalar_or_none(value: Any, field_name: str) -> float | str | None:
    if value is None:
        return None
    if isinstance(value, (int, float, str)):
        return value
    raise LlmOutputError(f"{field_name} must be number, string, or null.")
