"""Deterministic fake LLM backend for local smoke tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FakeLlmClient:
    """Return strict JSON without network access."""

    def generate_json(self, *, model: str, prompt: str) -> str:
        del model
        payload = _extract_payload(prompt)
        if "event-type resolver" in prompt:
            return json.dumps(_event_type_result(payload), ensure_ascii=False)
        if "PHR metric" in prompt or "\"phr_value_2025\"" in prompt:
            return json.dumps(_phr_result(payload), ensure_ascii=False)
        if "document-level verifier for one event" in prompt or "\"planned_value\"" in prompt:
            return json.dumps(_event_result(payload), ensure_ascii=False)
        raise ValueError("FakeLlmClient received unsupported prompt.")


def _extract_payload(prompt: str) -> dict[str, Any]:
    marker = "## Input payload"
    _, _, tail = prompt.partition(marker)
    if not tail.strip():
        raise ValueError("FakeLlmClient expected rendered payload in prompt.")
    return json.loads(tail.strip())


def _event_type_result(payload: dict[str, Any]) -> dict[str, str]:
    planned_value = _to_number(payload.get("planned_value"))
    event_type = "qualitative" if planned_value == 0 else "quantitative"
    return {
        "event_type": event_type,
        "reasoning": "Smoke backend inferred event type from planned_value.",
    }


def _event_result(payload: dict[str, Any]) -> dict[str, Any]:
    evidence_text = str(payload.get("evidence_text") or "")
    marker = _classify_marker(evidence_text)
    planned_value = _to_number(payload.get("planned_value"))
    planned_unit = _string_or_none(payload.get("planned_unit"))
    document_id = _string_or_none(payload.get("document_id"))
    file_name = str(payload.get("file_name") or "")

    if marker == "pass":
        observed_value = 15
        return {
            "document_id": document_id,
            "file_name": file_name,
            "fact_status": "подтверждено",
            "reasoning": "OCR прямо подтверждает выполнение мероприятия и перевыполнение плана.",
            "matched_action": "поставка",
            "matched_subject": "оборудования",
            "completion_signal": "выполнена",
            "observed_value": observed_value,
            "observed_unit": planned_unit,
            "comparison_result": "meets_target",
            "evidence_quote": _truncate_quote(evidence_text),
            "reasoning_trace": _trace(
                quote=_truncate_quote(evidence_text),
                reason_codes=["mentions_completion_fact", "mentions_event_result"],
                missing_requirements=[],
                short_rationale="OCR содержит факт выполнения и количество выше плана.",
                confidence="high",
            ),
        }
    if marker == "below_plan":
        observed_value = 8
        return {
            "document_id": document_id,
            "file_name": file_name,
            "fact_status": "не подтверждено",
            "reasoning": f"OCR подтверждает факт выполнения, но значение {observed_value} ниже плана {planned_value}.",
            "matched_action": "поставка",
            "matched_subject": "оборудования",
            "completion_signal": "выполнена",
            "observed_value": observed_value,
            "observed_unit": planned_unit,
            "comparison_result": "below_target",
            "evidence_quote": _truncate_quote(evidence_text),
            "reasoning_trace": _trace(
                quote=_truncate_quote(evidence_text),
                reason_codes=["mentions_completion_fact", "insufficient_evidence"],
                missing_requirements=["planned_value_reached"],
                short_rationale="OCR содержит количество ниже целевого значения.",
                confidence="high",
            ),
        }
    if marker == "semantic_only":
        return {
            "document_id": document_id,
            "file_name": file_name,
            "fact_status": "не подтверждено",
            "reasoning": "OCR подтверждает только факт выполнения без проверяемого количества.",
            "matched_action": "поставка",
            "matched_subject": "оборудования",
            "completion_signal": "выполнена",
            "observed_value": None,
            "observed_unit": None,
            "comparison_result": "insufficient_data",
            "evidence_quote": _truncate_quote(evidence_text),
            "reasoning_trace": _trace(
                quote=_truncate_quote(evidence_text),
                reason_codes=["mentions_completion_fact", "insufficient_evidence"],
                missing_requirements=["observed_value", "observed_unit"],
                short_rationale="В OCR нет числа и единицы измерения для количественного таргета.",
                confidence="medium",
            ),
        }
    return {
        "document_id": document_id,
        "file_name": file_name,
        "fact_status": "не подтверждено",
        "reasoning": "OCR не содержит достаточных признаков подтверждения.",
        "matched_action": None,
        "matched_subject": None,
        "completion_signal": None,
        "observed_value": None,
        "observed_unit": None,
        "comparison_result": "insufficient_data",
        "evidence_quote": None,
        "reasoning_trace": _trace(
            quote=None,
            reason_codes=["insufficient_evidence"],
            missing_requirements=["explicit evidence"],
            short_rationale="Подтверждающий OCR-фрагмент не найден.",
            confidence="low",
        ),
    }


def _phr_result(payload: dict[str, Any]) -> dict[str, Any]:
    evidence_text = str(payload.get("evidence_text") or "")
    marker = _classify_marker(evidence_text)
    phr_unit = _string_or_none(payload.get("phr_unit"))
    phr_name = _string_or_none(payload.get("phr_name"))
    document_id = _string_or_none(payload.get("document_id"))
    file_name = str(payload.get("file_name") or "")

    if marker == "pass":
        return {
            "document_id": document_id,
            "file_name": file_name,
            "phr_fact_status": "подтверждено",
            "reasoning": "OCR содержит явное количественное подтверждение ПХР.",
            "metric_matched": phr_name,
            "characteristic_explicitly_matched": True,
            "quantity_refers_to_metric_object": True,
            "observed_value": 15,
            "observed_unit": phr_unit,
            "comparison_result": "meets_target",
            "evidence_quote": _truncate_quote(evidence_text),
            "reasoning_trace": _trace(
                quote=_truncate_quote(evidence_text),
                reason_codes=["mentions_phr", "mentions_completion_fact"],
                missing_requirements=[],
                short_rationale="В OCR найдено значение ПХР выше плана.",
                confidence="high",
            ),
        }
    if marker == "below_plan":
        return {
            "document_id": document_id,
            "file_name": file_name,
            "phr_fact_status": "не подтверждено",
            "reasoning": "OCR содержит количество, но оно ниже требуемого значения ПХР.",
            "metric_matched": phr_name,
            "characteristic_explicitly_matched": True,
            "quantity_refers_to_metric_object": True,
            "observed_value": 8,
            "observed_unit": phr_unit,
            "comparison_result": "below_target",
            "evidence_quote": _truncate_quote(evidence_text),
            "reasoning_trace": _trace(
                quote=_truncate_quote(evidence_text),
                reason_codes=["mentions_phr", "insufficient_evidence"],
                missing_requirements=["planned_value_reached"],
                short_rationale="Количество ПХР ниже планового значения.",
                confidence="high",
            ),
        }
    return {
        "document_id": document_id,
        "file_name": file_name,
        "phr_fact_status": "не подтверждено",
        "reasoning": "OCR не доказывает количественное достижение ПХР.",
        "metric_matched": phr_name if marker == "semantic_only" else None,
        "characteristic_explicitly_matched": marker == "semantic_only",
        "quantity_refers_to_metric_object": False,
        "observed_value": None,
        "observed_unit": None,
        "comparison_result": "insufficient_data",
        "evidence_quote": _truncate_quote(evidence_text) if marker == "semantic_only" else None,
        "reasoning_trace": _trace(
            quote=_truncate_quote(evidence_text) if marker == "semantic_only" else None,
            reason_codes=["insufficient_evidence"],
            missing_requirements=["observed_value", "observed_unit"],
            short_rationale="В OCR нет достаточного количественного подтверждения ПХР.",
            confidence="medium" if marker == "semantic_only" else "low",
        ),
    }


def _trace(
    *,
    quote: str | None,
    reason_codes: list[str],
    missing_requirements: list[str],
    short_rationale: str,
    confidence: str,
) -> dict[str, Any]:
    evidence_items = []
    if quote is not None:
        evidence_items.append(
            {
                "quote": quote,
                "page": None,
                "source": "ocr",
                "why_relevant": "Smoke OCR evidence",
            }
        )
    return {
        "reason_codes": reason_codes,
        "evidence_items": evidence_items,
        "missing_requirements": missing_requirements,
        "short_rationale": short_rationale,
        "confidence": confidence,
    }


def _classify_marker(evidence_text: str) -> str:
    normalized = evidence_text.lower()
    if "smoke_pass_overfulfilled" in normalized or ("15" in normalized and "12" in normalized):
        return "pass"
    if "smoke_below_plan" in normalized or ("8" in normalized and "12" in normalized):
        return "below_plan"
    if "smoke_semantic_only" in normalized or "поставка выполнена" in normalized:
        return "semantic_only"
    return "unknown"


def _truncate_quote(text: str) -> str | None:
    cleaned = " ".join(text.split())
    return cleaned[:220] if cleaned else None


def _to_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    rendered = str(value).strip().replace(",", ".")
    if not rendered:
        return None
    return float(rendered)


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    rendered = str(value).strip()
    return rendered or None
