from __future__ import annotations

from pathlib import Path

from fakes import build_app, ocr_file, phr_result


def test_malformed_json_retry_can_recover(tmp_path: Path) -> None:
    app, _ = build_app(
        tmp_path,
        responses=[
            "not json",
            '{"document_id":"doc-1","file_name":"report-1.pdf","fact_status":"подтверждено","reasoning":"event reasoning","matched_action":"построить","matched_subject":"объект","completion_signal":"введено","observed_value":2,"observed_unit":"ед","comparison_result":"meets_target","evidence_quote":"введены 2 объекта","reasoning_trace":{"reason_codes":["mentions_completion_fact"],"evidence_items":[{"quote":"введены 2 объекта","page":null,"source":"ocr","why_relevant":"relevant"}],"missing_requirements":[],"short_rationale":"trace","confidence":"high"}}',
            "not json",
            phr_result(confirmed=True, comparison_result="meets_target", quote="введены 2 объекта"),
        ],
        files=[ocr_file("doc-1", "report-1.pdf", "ocr text")],
    )

    artifacts = app.verify(
        event_id=42,
        output_dir=tmp_path / "output",
        primary_model="primary",
        audit_model="audit",
        export_xlsx=False,
    )

    assert artifacts.result_json["statuses"]["event_description_status"] == "Подтверждено"
    assert artifacts.result_json["statuses"]["phr_status"] == "Подтверждено"
