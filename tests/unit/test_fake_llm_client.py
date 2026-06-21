from __future__ import annotations

import json

from buratino.llm.fake_client import FakeLlmClient


def _prompt(template_intro: str, payload: dict) -> str:
    return f"{template_intro}\n\n## Input payload\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n"


def test_fake_llm_client_returns_confirmed_event_json() -> None:
    client = FakeLlmClient()

    response = client.generate_json(
        model="fake/buratino-smoke-model",
        prompt=_prompt(
            "You are a document-level verifier for one event.",
            {
                "document_id": "doc-1",
                "file_name": "smoke-1001.pdf",
                "planned_value": 12,
                "planned_unit": "ед",
                "evidence_text": "SMOKE_PASS_OVERFULFILLED Поставка выполнена в объеме 15 ед. при плане 12 ед.",
            },
        ),
    )

    data = json.loads(response)
    assert data["fact_status"] == "подтверждено"
    assert data["comparison_result"] == "meets_target"
    assert data["observed_value"] == 15


def test_fake_llm_client_returns_semantic_only_phr_json() -> None:
    client = FakeLlmClient()

    response = client.generate_json(
        model="fake/buratino-smoke-model",
        prompt=_prompt(
            "You are a strict document-level verifier for one PHR metric.",
            {
                "document_id": "doc-2",
                "file_name": "smoke-1002.pdf",
                "phr_name": "Количество поставленного оборудования",
                "phr_value_2025": 12,
                "phr_unit": "ед",
                "evidence_text": "SMOKE_SEMANTIC_ONLY Поставка выполнена, оборудование поставлено.",
            },
        ),
    )

    data = json.loads(response)
    assert data["phr_fact_status"] == "не подтверждено"
    assert data["comparison_result"] == "insufficient_data"
    assert data["observed_value"] is None
