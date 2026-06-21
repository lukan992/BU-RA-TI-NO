from __future__ import annotations

from pathlib import Path

from fakes import build_app, ocr_file, summary_only_file


def test_summary_only_document_is_not_used_for_verdict(tmp_path: Path) -> None:
    app, llm = build_app(
        tmp_path,
        responses=[],
        files=[summary_only_file("doc-1", "report-1.pdf", "summary text only")],
    )

    artifacts = app.verify(
        event_id=42,
        output_dir=tmp_path / "output",
        primary_model="primary",
        audit_model="audit",
        export_xlsx=False,
    )

    assert artifacts.result_json["statuses"]["event_description_status"] == "Не подтверждено"
    assert artifacts.result_json["diagnostics"]["skipped_files"] == ["report-1.pdf"]
    assert llm.prompts == []


def test_ranking_disabled_still_analyzes_all_ocr_documents(tmp_path: Path) -> None:
    event_confirmed = '{"document_id":"doc-1","file_name":"report-1.pdf","fact_status":"не подтверждено","reasoning":"event reasoning","matched_action":"построить","matched_subject":"объект","completion_signal":null,"observed_value":null,"observed_unit":null,"comparison_result":"insufficient_data","evidence_quote":null,"reasoning_trace":{"reason_codes":["insufficient_evidence"],"evidence_items":[],"missing_requirements":["explicit evidence"],"short_rationale":"trace","confidence":"low"}}'
    phr_negative = '{"document_id":"doc-1","file_name":"report-1.pdf","phr_fact_status":"не подтверждено","reasoning":"phr reasoning","metric_matched":null,"characteristic_explicitly_matched":false,"quantity_refers_to_metric_object":false,"observed_value":null,"observed_unit":null,"comparison_result":"insufficient_data","evidence_quote":null,"reasoning_trace":{"reason_codes":["insufficient_evidence"],"evidence_items":[],"missing_requirements":["explicit evidence"],"short_rationale":"trace","confidence":"low"}}'
    app, llm = build_app(
        tmp_path,
        responses=[event_confirmed, event_confirmed, phr_negative, phr_negative],
        files=[
            ocr_file("doc-1", "report-1.pdf", "ocr 1"),
            ocr_file("doc-2", "report-2.pdf", "ocr 2"),
        ],
    )

    app.verify(
        event_id=42,
        output_dir=tmp_path / "output",
        primary_model="primary",
        audit_model="audit",
        export_xlsx=False,
    )

    assert len(llm.prompts) == 4
