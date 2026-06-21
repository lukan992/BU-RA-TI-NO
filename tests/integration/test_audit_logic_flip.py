from __future__ import annotations

from pathlib import Path

from fakes import build_app, event_result, ocr_file, phr_result


def test_audit_is_disabled_and_does_not_appear_in_result_model_info(tmp_path: Path) -> None:
    app, _ = build_app(
        tmp_path,
        responses=[
            event_result(confirmed=False, comparison_result="insufficient_data", quote=None, observed_value=None, observed_unit=None),
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

    assert artifacts.result_json["model_info"]["audit_model"] is None
