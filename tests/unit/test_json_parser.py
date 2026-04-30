from __future__ import annotations

import pytest

from buratino.llm.json_parser import (
    parse_audit_result,
    parse_confirming_documents_relation_result,
    parse_event_document_result,
    parse_phr_document_result,
)
from buratino.models.errors import LlmOutputError


def test_parse_event_document_result_rejects_malformed_json() -> None:
    with pytest.raises(LlmOutputError, match="Malformed JSON"):
        parse_event_document_result("{bad json")


def test_parse_event_document_result_rejects_extra_keys() -> None:
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
      "extra": "bad"
    }
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
      "evidence_quote": "поставлено 20 БАС мультироторного типа"
    }
    """

    result = parse_phr_document_result(payload)

    assert result.phr_fact_status == "подтверждено"
    assert result.characteristic_explicitly_matched is True
    assert result.quantity_refers_to_metric_object is True


def test_parse_phr_document_result_rejects_extra_keys() -> None:
    payload = """
    {
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
      "extra": "bad"
    }
    """

    with pytest.raises(LlmOutputError, match="extra keys"):
        parse_phr_document_result(payload)


def test_parse_phr_document_result_rejects_missing_keys() -> None:
    payload = """
    {
      "document_id": "1",
      "file_name": "doc.pdf",
      "phr_fact_status": "не подтверждено",
      "reasoning": "generic object only",
      "metric_matched": "БАС",
      "characteristic_explicitly_matched": false,
      "observed_value": 20,
      "observed_unit": "шт",
      "comparison_result": "insufficient_data",
      "evidence_quote": null
    }
    """

    with pytest.raises(LlmOutputError, match="missing keys: quantity_refers_to_metric_object"):
        parse_phr_document_result(payload)


def test_parse_audit_result_rejects_extra_keys() -> None:
    payload = """
    {
      "logic_is_valid": true,
      "detected_errors": [],
      "corrected_event_status": "не подтверждено",
      "corrected_phr_status": "не подтверждено",
      "corrected_reasoning": "valid",
      "extra": "bad"
    }
    """

    with pytest.raises(LlmOutputError, match="extra keys"):
        parse_audit_result(payload)


def test_parse_audit_result_accepts_not_indicated_phr_status() -> None:
    payload = """
    {
      "logic_is_valid": true,
      "detected_errors": [],
      "corrected_event_status": "не подтверждено",
      "corrected_phr_status": "не указано",
      "corrected_reasoning": "phr is not defined"
    }
    """

    result = parse_audit_result(payload)

    assert result.corrected_phr_status == "не указано"


def test_parse_confirming_documents_relation_result_accepts_related() -> None:
    payload = """
    {
      "event_id": 1,
      "file_ids": "doc-1,doc-2",
      "reasoning": "documents match event",
      "relation_status": "относится"
    }
    """

    result = parse_confirming_documents_relation_result(payload)

    assert result.file_ids == "doc-1,doc-2"
    assert result.relation_status == "относится"


def test_parse_confirming_documents_relation_result_rejects_insufficient_data() -> None:
    payload = """
    {
      "event_id": 1,
      "file_ids": "doc-1",
      "reasoning": "not enough evidence",
      "relation_status": "недостаточно данных"
    }
    """

    with pytest.raises(LlmOutputError, match="relation_status"):
        parse_confirming_documents_relation_result(payload)
