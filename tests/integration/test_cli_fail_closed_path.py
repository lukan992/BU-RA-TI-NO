from __future__ import annotations

from pathlib import Path

from fakes import build_app, event_result, ocr_file, phr_result, summary_only_file


def test_no_ocr_documents_complete_with_negative_business_result(tmp_path: Path) -> None:
    app, llm = build_app(
        tmp_path,
        responses=[],
        files=[summary_only_file("doc-1", "report-1.pdf", "summary only")],
    )

    artifacts = app.verify(
        event_id=42,
        output_dir=tmp_path / "output",
        primary_model="primary",
        audit_model="audit",
        export_xlsx=False,
    )

    assert artifacts.result_json["statuses"] == {
        "event_description_status": "Не подтверждено",
        "phr_status": "Не подтверждено",
        "plan_status": "Не подтверждено",
    }
    assert artifacts.result_json["diagnostics"]["diagnostic_reason"] == "OCR отсутствует"
    assert llm.prompts == []


def test_semantic_match_without_target_keeps_event_and_plan_negative(tmp_path: Path) -> None:
    app, _ = build_app(
        tmp_path,
        responses=[
            event_result(confirmed=True, comparison_result="below_target", quote="построен 1 объект", observed_value=1),
            phr_result(confirmed=False, comparison_result="insufficient_data", quote=None),
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

    assert artifacts.result_json["statuses"]["event_description_status"] == "Не подтверждено"
    assert artifacts.result_json["statuses"]["plan_status"] == "Не подтверждено"
