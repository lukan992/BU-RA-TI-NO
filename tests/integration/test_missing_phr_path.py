from __future__ import annotations

from pathlib import Path

from buratino.models.domain import PhrRecord
from fakes import FakeEventRepository, build_app, event_result, ocr_file


def test_missing_phr_is_reported_as_not_applicable(tmp_path: Path) -> None:
    app, _ = build_app(
        tmp_path,
        responses=[
            event_result(confirmed=True, comparison_result="meets_target", quote="введены 2 объекта"),
        ],
        files=[ocr_file("doc-1", "report-1.pdf", "ocr text")],
        event_repository=FakeEventRepository(missing_phr=True),
    )

    artifacts = app.verify(
        event_id=42,
        output_dir=tmp_path / "output",
        primary_model="primary",
        audit_model="audit",
        export_xlsx=False,
    )

    assert artifacts.result_json["statuses"]["phr_status"] == "Не применимо"
