from __future__ import annotations

from pathlib import Path

from fakes import build_app, event_result, ocr_file, phr_result, summary_only_file


def test_diagnostics_list_analyzed_and_skipped_files(tmp_path: Path) -> None:
    app, _ = build_app(
        tmp_path,
        responses=[
            event_result(confirmed=False, comparison_result="insufficient_data", quote=None, observed_value=None, observed_unit=None),
            phr_result(confirmed=False, comparison_result="insufficient_data", quote=None),
        ],
        files=[
            ocr_file("doc-1", "ocr.pdf", "ocr text"),
            summary_only_file("doc-2", "summary.pdf", "summary text"),
        ],
    )

    artifacts = app.verify(
        event_id=42,
        output_dir=tmp_path / "output",
        primary_model="primary",
        audit_model="audit",
        export_xlsx=False,
    )

    assert artifacts.result_json["diagnostics"]["ocr_available"] is True
    assert artifacts.result_json["diagnostics"]["analyzed_files"] == ["ocr.pdf"]
    assert artifacts.result_json["diagnostics"]["skipped_files"] == ["summary.pdf"]
