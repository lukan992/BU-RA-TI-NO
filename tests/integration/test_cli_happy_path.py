from __future__ import annotations

from pathlib import Path

from fakes import build_app, event_result, ocr_file, phr_result


def test_happy_path_generates_new_result_json_and_xlsx(tmp_path: Path) -> None:
    app, _ = build_app(
        tmp_path,
        responses=[
            event_result(confirmed=True, comparison_result="meets_target", quote="введены 2 объекта"),
            event_result(confirmed=False, comparison_result="insufficient_data", quote=None, observed_value=None, observed_unit=None),
            phr_result(confirmed=True, comparison_result="meets_target", quote="введены 2 объекта"),
            phr_result(confirmed=False, comparison_result="insufficient_data", quote=None),
        ],
        files=[
            ocr_file("doc-1", "report-1.pdf", "ocr 1", summary_text="summary 1"),
            ocr_file("doc-2", "report-2.pdf", "ocr 2", summary_text="summary 2"),
        ],
    )

    artifacts = app.verify(
        event_id=42,
        output_dir=tmp_path / "output",
        primary_model="primary",
        audit_model="audit",
        export_xlsx=True,
    )

    assert artifacts.result_json["statuses"]["event_description_status"] == "Подтверждено"
    assert artifacts.result_json["statuses"]["phr_status"] == "Подтверждено"
    assert artifacts.result_json["statuses"]["plan_status"] == "Подтверждено"
    assert artifacts.result_json["supporting_files"][0]["filename"] == "report-1.pdf"
    assert artifacts.result_json["model_info"]["audit_model"] is None
    assert artifacts.json_path.exists()
    assert artifacts.xlsx_path is not None and artifacts.xlsx_path.exists()
