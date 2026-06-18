from __future__ import annotations

from pathlib import Path


PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


def test_prompt_contracts_cover_parser_required_keys() -> None:
    prompt_expectations = {
        "document_ranking.md": [
            "ranked_documents",
            "doc_id",
            "score",
            "reason_codes",
            "short_reason",
        ],
        "event_fact_summary.md": [
            "fact_status",
            "matched_action",
            "matched_subject",
            "completion_signal",
            "observed_value",
            "observed_unit",
            "comparison_result",
            "evidence_quote",
            "reasoning_trace",
            "reason_codes",
            "evidence_items",
            "missing_requirements",
            "short_rationale",
            "confidence",
        ],
        "phr_fact_summary.md": [
            "phr_fact_status",
            "metric_matched",
            "characteristic_explicitly_matched",
            "quantity_refers_to_metric_object",
            "observed_value",
            "observed_unit",
            "comparison_result",
            "evidence_quote",
            "reasoning_trace",
            "reason_codes",
            "evidence_items",
            "missing_requirements",
            "short_rationale",
            "confidence",
        ],
        "confirming_documents_relation.md": [
            "documents",
            "doc_id",
            "relation_to_event",
            "relation_reason",
        ],
        "event_type_resolution.md": [
            "event_type",
            "reasoning",
        ],
        "logic_audit.md": [
            "audit_result",
            "rule_violations",
            "affected_field",
            "from",
            "to",
            "reason",
            "final_event_fact_status",
            "final_phr_fact_status",
            "final_supporting_files",
        ],
    }

    for prompt_name, tokens in prompt_expectations.items():
        prompt_text = (PROMPTS_DIR / prompt_name).read_text(encoding="utf-8")
        for token in tokens:
            assert token in prompt_text, f"{prompt_name} is missing required token: {token}"
