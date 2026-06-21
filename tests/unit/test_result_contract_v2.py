from __future__ import annotations

import pytest

from buratino.models.errors import ValidationError
from buratino.models.result_contract import validate_result_json


def test_validate_result_json_accepts_minimal_valid_payload() -> None:
    payload = {
        "pipeline_name": "buratino",
        "pipeline_version": "0.1.0",
        "event_id": 42,
        "report_id": None,
        "result_value_id": None,
        "event_name": "event",
        "statuses": {
            "event_description_status": "Не подтверждено",
            "phr_status": "Не применимо",
            "plan_status": "Не подтверждено",
        },
        "expected": {
            "event_description": "desc",
            "phr": None,
            "plan": "2 ед",
        },
        "facts": {
            "event_description_fact": None,
            "phr_fact": None,
            "plan_fact": None,
        },
        "supporting_files": [],
        "evidence_items": [],
        "diagnostics": {
            "evidence_source_used": "ocr",
            "ocr_available": False,
            "analyzed_files": [],
            "skipped_files": [],
            "diagnostic_reason": "OCR отсутствует",
        },
        "model_info": {
            "primary_model": "primary",
            "ranking_model": None,
            "audit_model": None,
        },
    }

    validate_result_json(payload)


def test_validate_result_json_rejects_summary_evidence_source() -> None:
    payload = {
        "pipeline_name": "buratino",
        "pipeline_version": "0.1.0",
        "event_id": 42,
        "report_id": None,
        "result_value_id": None,
        "event_name": "event",
        "statuses": {
            "event_description_status": "Не подтверждено",
            "phr_status": "Не применимо",
            "plan_status": "Не подтверждено",
        },
        "expected": {
            "event_description": "desc",
            "phr": None,
            "plan": "2 ед",
        },
        "facts": {
            "event_description_fact": None,
            "phr_fact": None,
            "plan_fact": None,
        },
        "supporting_files": [],
        "evidence_items": [],
        "diagnostics": {
            "evidence_source_used": "summary",
            "ocr_available": False,
            "analyzed_files": [],
            "skipped_files": [],
            "diagnostic_reason": "bad",
        },
        "model_info": {
            "primary_model": "primary",
            "ranking_model": None,
            "audit_model": None,
        },
    }

    with pytest.raises(ValidationError, match="evidence_source_used"):
        validate_result_json(payload)
