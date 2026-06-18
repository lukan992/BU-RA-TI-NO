from __future__ import annotations

import pytest

from buratino.llm.json_parser import (
    parse_audit_result,
    parse_confirming_documents_relation_result,
    parse_event_document_result,
    parse_phr_document_result,
    TraceLimits,
)
from buratino.models.errors import LlmOutputError


def _trace_payload() -> str:
    return """
    "reasoning_trace": {
      "reason_codes": ["insufficient_evidence"],
      "evidence_items": [],
      "missing_requirements": ["explicit completion"],
      "short_rationale": "Нет явного подтверждения.",
      "confidence": "low"
    }
    """


def test_parse_event_document_result_rejects_malformed_json() -> None:
    with pytest.raises(LlmOutputError, match="Malformed JSON"):
        parse_event_document_result("{bad json")


def test_parse_event_document_result_rejects_extra_keys() -> None:
    payload = f"""
    {{
      "document_id": "1",
      "file_name": "doc.pdf",
      "fact_status": "не подтверждено",
      "reasoning": "not enough evidence",
      "matched_action": null,
      "matched_subject": null,
      "completion_signal": null,
      "observed_value": null,
      "observed_unit": null,
      "comparison_result": "insufficient_data",
      "evidence_quote": null,
      {_trace_payload()},
      "extra": "bad"
    }}
    """

    with pytest.raises(LlmOutputError, match="extra keys"):
        parse_event_document_result(payload)


def test_parse_phr_document_result_accepts_updated_schema() -> None:
    payload = """
    {
      "document_id": "1",
      "file_name": "doc.pdf",
      "phr_fact_status": "подтверждено",
      "reasoning": "metric object and quantity are explicit",
      "metric_matched": "БАС мультироторного типа",
      "characteristic_explicitly_matched": true,
      "quantity_refers_to_metric_object": true,
      "observed_value": 20,
      "observed_unit": "шт",
      "comparison_result": "meets_target",
      "evidence_quote": "поставлено 20 БАС мультироторного типа",
      "reasoning_trace": {
        "reason_codes": ["mentions_phr"],
        "evidence_items": [
          {
            "quote": "поставлено 20 БАС мультироторного типа",
            "page": null,
            "source": "summary",
            "why_relevant": "Есть прямой факт поставки."
          }
        ],
        "missing_requirements": [],
        "short_rationale": "Документ прямо подтверждает достижение ПХР.",
        "confidence": "high"
      }
    }
    """

    result = parse_phr_document_result(payload)

    assert result.phr_fact_status == "подтверждено"
    assert result.characteristic_explicitly_matched is True
    assert result.quantity_refers_to_metric_object is True
    assert len(result.reasoning_trace.evidence_items) == 1


def test_parse_phr_document_result_normalizes_not_applicable_to_insufficient_data() -> None:
    payload = """
    {
      "document_id": "1",
      "file_name": "doc.pdf",
      "phr_fact_status": "не подтверждено",
      "reasoning": "metric object is not explicit",
      "metric_matched": null,
      "characteristic_explicitly_matched": false,
      "quantity_refers_to_metric_object": false,
      "observed_value": null,
      "observed_unit": null,
      "comparison_result": "not_applicable",
      "evidence_quote": null,
      "reasoning_trace": {
        "reason_codes": ["insufficient_evidence"],
        "evidence_items": [],
        "missing_requirements": ["explicit metric match"],
        "short_rationale": "Нет достаточных данных для подтверждения.",
        "confidence": "low"
      }
    }
    """

    result = parse_phr_document_result(payload)

    assert result.comparison_result == "insufficient_data"


def test_parse_phr_document_result_rejects_extra_keys() -> None:
    payload = f"""
    {{
      "document_id": "1",
      "file_name": "doc.pdf",
      "phr_fact_status": "не подтверждено",
      "reasoning": "generic object only",
      "metric_matched": "БАС",
      "characteristic_explicitly_matched": false,
      "quantity_refers_to_metric_object": true,
      "observed_value": 20,
      "observed_unit": "шт",
      "comparison_result": "insufficient_data",
      "evidence_quote": null,
      {_trace_payload()},
      "extra": "bad"
    }}
    """

    with pytest.raises(LlmOutputError, match="extra keys"):
        parse_phr_document_result(payload)


def test_parse_phr_document_result_rejects_missing_keys() -> None:
    payload = f"""
    {{
      "document_id": "1",
      "file_name": "doc.pdf",
      "phr_fact_status": "не подтверждено",
      "reasoning": "generic object only",
      "metric_matched": "БАС",
      "characteristic_explicitly_matched": false,
      "observed_value": 20,
      "observed_unit": "шт",
      "comparison_result": "insufficient_data",
      "evidence_quote": null,
      {_trace_payload()}
    }}
    """

    with pytest.raises(LlmOutputError, match="missing keys: quantity_refers_to_metric_object"):
        parse_phr_document_result(payload)


def test_parse_event_document_result_rejects_too_many_evidence_items() -> None:
    payload = """
    {
      "document_id": "1",
      "file_name": "doc.pdf",
      "fact_status": "подтверждено",
      "reasoning": "document confirms event",
      "matched_action": "Построить",
      "matched_subject": "объект",
      "completion_signal": "выполнено",
      "observed_value": 1,
      "observed_unit": "ед",
      "comparison_result": "meets_target",
      "evidence_quote": "выполнено",
      "reasoning_trace": {
        "reason_codes": ["mentions_event_result"],
        "evidence_items": [
          {"quote": "a", "page": null, "source": "summary", "why_relevant": "1"},
          {"quote": "b", "page": null, "source": "summary", "why_relevant": "2"}
        ],
        "missing_requirements": [],
        "short_rationale": "ok",
        "confidence": "high"
      }
    }
    """

    with pytest.raises(LlmOutputError, match="at most 1 items"):
        parse_event_document_result(payload, trace_limits=TraceLimits(max_items=1))


def test_parse_event_document_result_rejects_long_short_rationale() -> None:
    payload = """
    {
      "document_id": "1",
      "file_name": "doc.pdf",
      "fact_status": "не подтверждено",
      "reasoning": "not enough evidence",
      "matched_action": null,
      "matched_subject": null,
      "completion_signal": null,
      "observed_value": null,
      "observed_unit": null,
      "comparison_result": "insufficient_data",
      "evidence_quote": null,
      "reasoning_trace": {
        "reason_codes": ["insufficient_evidence"],
        "evidence_items": [],
        "missing_requirements": [],
        "short_rationale": "слишком длинно",
        "confidence": "low"
      }
    }
    """

    with pytest.raises(LlmOutputError, match="short_rationale must be at most 3 characters"):
        parse_event_document_result(payload, trace_limits=TraceLimits(short_rationale_max_chars=3))


def test_parse_audit_result_rejects_extra_keys() -> None:
    payload = """
    {
      "audit_result": "pass",
      "rule_violations": [],
      "final_event_fact_status": "не подтверждено",
      "final_phr_fact_status": "не подтверждено",
      "final_supporting_files": [],
      "extra": "bad"
    }
    """

    with pytest.raises(LlmOutputError, match="extra keys"):
        parse_audit_result(payload)


def test_parse_audit_result_accepts_not_indicated_phr_status() -> None:
    payload = """
    {
      "audit_result": "pass",
      "rule_violations": [],
      "final_event_fact_status": "не подтверждено",
      "final_phr_fact_status": "не указано",
      "final_supporting_files": []
    }
    """

    result = parse_audit_result(payload)

    assert result.corrected_phr_status == "не указано"
    assert result.logic_is_valid is True


def test_parse_confirming_documents_relation_result_accepts_related() -> None:
    payload = """
    {
      "documents": [
        {
          "doc_id": "doc-1",
          "relation_to_event": "direct",
          "relation_reason": "documents match event"
        }
      ]
    }
    """

    result = parse_confirming_documents_relation_result(payload)

    assert result.documents[0]["doc_id"] == "doc-1"
    assert result.documents[0]["relation_to_event"] == "direct"


def test_parse_confirming_documents_relation_result_rejects_invalid_relation() -> None:
    payload = """
    {
      "documents": [
        {
          "doc_id": "doc-1",
          "relation_to_event": "related",
          "relation_reason": "not enough evidence"
        }
      ]
    }
    """

    with pytest.raises(LlmOutputError, match="relation_to_event"):
        parse_confirming_documents_relation_result(payload)
