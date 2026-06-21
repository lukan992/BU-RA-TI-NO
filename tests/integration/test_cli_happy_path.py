from __future__ import annotations

import json
from pathlib import Path

from buratino.app import VerificationApp
from buratino.audit.service import AuditService
from buratino.llm.prompt_loader import PromptLoader
from buratino.models.domain import DocumentSummary, EventRecord, PhrRecord
from buratino.target_builder.service import TargetBuilder
from buratino.verifier.document_ranking import DocumentRankingService
from buratino.verifier.event_verifier import EventVerifier
from buratino.verifier.phr_verifier import PhrVerifier
from conftest import create_prompt_assets


class FakeEventRepository:
    def get_event(self, event_id: int) -> EventRecord:
        return EventRecord(
            event_id=event_id,
            event_name="Построить спортивный объект",
            event_description="Построить объект и ввести его в эксплуатацию",
            planned_value=2,
            planned_unit="ед",
        )

    def get_event_phr(self, event_id: int) -> PhrRecord:
        return PhrRecord(
            event_id=event_id,
            phr_name="Количество введенных объектов",
            phr_value_2025=2,
            phr_unit="ед",
        )


class FakeSummaryRepository:
    def list_event_documents(self, event_id: int) -> list[DocumentSummary]:
        return [
            DocumentSummary("doc-1", "report-1.pdf", "ocr 1", "ocr", ocr_text="ocr 1", summary_text="summary 1", ocr_parts=("ocr 1",)),
            DocumentSummary("doc-2", "report-2.pdf", "ocr 2", "ocr", ocr_text="ocr 2", summary_text="summary 2", ocr_parts=("ocr 2",)),
        ]

    def get_document_date_texts(self, document_ids: list[str]) -> dict[str, str | None]:
        return {"doc-1": "Дата документа: 25.12.2025 номер 1"}


class SequencedLlmClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.prompts: list[str] = []

    def generate_json(self, *, model: str, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._responses.pop(0)


def test_happy_path_generates_json_and_xlsx(tmp_path: Path) -> None:
    app = _build_app(
        tmp_path,
        [
            _event_result("doc-1", "report-1.pdf", True, "введены 2 объекта"),
            _event_result("doc-2", "report-2.pdf", False, None),
            _phr_result("doc-1", "report-1.pdf", True, "введены 2 объекта"),
            _phr_result("doc-2", "report-2.pdf", False, None),
        ],
        summary_repository=FakeSummaryRepository(),
    )

    artifacts = app.verify(
        event_id=42,
        output_dir=tmp_path / "output",
        primary_model="primary",
        audit_model="audit",
        export_xlsx=True,
    )

    assert artifacts.report.event_fact_status == "подтверждено"
    assert artifacts.report.phr_fact_status == "подтверждено"
    assert artifacts.report.supporting_files == ["report-1.pdf"]
    assert "report-1.pdf" in artifacts.report.event_reasoning
    assert "введены 2 объекта" in artifacts.report.event_reasoning
    assert "summary документа" not in artifacts.report.event_reasoning
    assert artifacts.report.confirming_documents_relation is None
    assert artifacts.report.evidence_trace.event_fact
    assert artifacts.report.logic_is_valid == "not_checked"
    assert artifacts.json_path.exists()
    assert artifacts.xlsx_path is not None and artifacts.xlsx_path.exists()


def test_supporting_files_include_all_decision_significant_event_documents(tmp_path: Path) -> None:
    class CompositeSummaryRepository(FakeSummaryRepository):
        def list_event_documents(self, event_id: int) -> list[DocumentSummary]:
            return [
                DocumentSummary("doc-1", "contract.pdf", "ocr contract", "ocr", ocr_text="ocr contract", summary_text="summary contract", ocr_parts=("ocr contract",)),
                DocumentSummary("doc-2", "act.pdf", "ocr act", "ocr", ocr_text="ocr act", summary_text="summary act", ocr_parts=("ocr act",)),
            ]

        def get_document_date_texts(self, document_ids: list[str]) -> dict[str, str | None]:
            return {
                "doc-1": "Дата документа: 24.12.2025 номер 1",
                "doc-2": "Дата документа: 25.12.2025 номер 2",
            }

    app = _build_app(
        tmp_path,
        [
            _event_result("doc-1", "contract.pdf", True, "заключен договор на строительство двух объектов"),
            _event_result("doc-2", "act.pdf", True, "подписан акт приемки двух объектов"),
            _phr_result("doc-1", "contract.pdf", False, None),
            _phr_result("doc-2", "act.pdf", False, None),
        ],
        summary_repository=CompositeSummaryRepository(),
    )

    artifacts = app.verify(
        event_id=42,
        output_dir=tmp_path / "output",
        primary_model="primary",
        audit_model="audit",
        export_xlsx=False,
    )

    assert artifacts.report.event_fact_status == "подтверждено"
    assert artifacts.report.phr_fact_status == "не подтверждено"
    assert artifacts.report.supporting_files == ["contract.pdf", "act.pdf"]
    assert "contract.pdf" in artifacts.report.event_reasoning or "act.pdf" in artifacts.report.event_reasoning


def test_zero_target_phr_is_auto_confirmed_without_primary_phr_llm(tmp_path: Path) -> None:
    class ZeroPhrEventRepository(FakeEventRepository):
        def get_event(self, event_id: int) -> EventRecord:
            return EventRecord(
                event_id=event_id,
                event_name="Провести мероприятие",
                event_description="Провести мероприятие и зафиксировать факт исполнения",
                planned_value=0,
                planned_unit="шт",
            )

        def get_event_phr(self, event_id: int) -> PhrRecord:
            return PhrRecord(
                event_id=event_id,
                phr_name="Количество отклонений",
                phr_value_2025=0,
                phr_unit=None,
            )

    app = _build_app(
        tmp_path,
        [
            _event_result("doc-1", "report-1.pdf", True, "мероприятие выполнено"),
            _event_result("doc-2", "report-2.pdf", False, None),
        ],
        event_repository=ZeroPhrEventRepository(),
        summary_repository=FakeSummaryRepository(),
    )

    artifacts = app.verify(
        event_id=43,
        output_dir=tmp_path / "output",
        primary_model="primary",
        audit_model="audit",
        export_xlsx=False,
    )

    assert artifacts.report.phr_fact_status == "подтверждено"
    assert artifacts.report.phr_documents == []
    assert "требуемое значение равно 0" in artifacts.report.phr_reasoning


def test_ranking_selects_top_documents_before_analysis(tmp_path: Path) -> None:
    class RankingSummaryRepository(FakeSummaryRepository):
        def list_event_documents(self, event_id: int) -> list[DocumentSummary]:
            return [
                DocumentSummary("doc-1", "report-1.pdf", "ocr 1", "ocr", ocr_text="ocr 1", summary_text="summary 1", ocr_parts=("ocr 1",)),
                DocumentSummary("doc-2", "report-2.pdf", "ocr 2", "ocr", ocr_text="ocr 2", summary_text="summary 2", ocr_parts=("ocr 2",)),
                DocumentSummary("doc-3", "report-3.pdf", "ocr 3", "ocr", ocr_text="ocr 3", summary_text="summary 3", ocr_parts=("ocr 3",)),
            ]

        def get_document_date_texts(self, document_ids: list[str]) -> dict[str, str | None]:
            return {}

    app = _build_app(
        tmp_path,
        [
            json.dumps(
                {
                    "ranked_documents": [
                        {
                            "doc_id": "doc-2",
                            "score": 20,
                            "reason_codes": ["event_completion_candidate"],
                            "short_reason": "Most relevant.",
                        },
                        {
                            "doc_id": "doc-1",
                            "score": 10,
                            "reason_codes": ["event_completion_candidate"],
                            "short_reason": "Second most relevant.",
                        },
                    ]
                }
            ),
            _event_result("doc-2", "report-2.pdf", True, "введены 2 объекта"),
            _event_result("doc-1", "report-1.pdf", False, None),
            _phr_result("doc-2", "report-2.pdf", True, "введены 2 объекта"),
            _phr_result("doc-1", "report-1.pdf", False, None),
        ],
        summary_repository=RankingSummaryRepository(),
    )

    artifacts = app.verify(
        event_id=42,
        output_dir=tmp_path / "output",
        primary_model="primary",
        audit_model="audit",
        export_xlsx=False,
        max_documents_to_analyze=2,
    )

    assert artifacts.report.event_fact_status == "подтверждено"
    assert [document.file_name for document in artifacts.report.event_documents] == ["report-2.pdf", "report-1.pdf"]
    assert not any("report-3.pdf" in prompt for prompt in app.event_verifier.llm_client.prompts[1:])


def _build_app(
    tmp_path: Path,
    responses: list[str],
    *,
    event_repository=None,
    summary_repository=None,
) -> VerificationApp:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    create_prompt_assets(prompts_dir)
    llm = SequencedLlmClient(responses)
    prompt_loader = PromptLoader(prompts_dir)
    repository = summary_repository or FakeSummaryRepository()
    return VerificationApp(
        event_repository=event_repository or FakeEventRepository(),
        summary_repository=repository,
        target_builder=TargetBuilder(prompt_loader, llm, "primary"),
        document_ranking_service=DocumentRankingService(prompt_loader, llm, "ranking"),
        event_verifier=EventVerifier(prompt_loader, llm, "primary"),
        phr_verifier=PhrVerifier(prompt_loader, llm, "primary"),
        audit_service=AuditService(prompt_loader, llm, "audit"),
        ranking_enabled=True,
    )


def _reasoning_trace(confirmed: bool, quote: str | None = None) -> dict[str, object]:
    return {
        "reason_codes": ["mentions_completion_fact"] if confirmed else ["insufficient_evidence"],
        "evidence_items": (
            [
                {
                    "quote": quote or "evidence",
                    "page": None,
                    "source": "ocr",
                    "why_relevant": "Decision-significant evidence.",
                }
            ]
            if confirmed and quote is not None
            else []
        ),
        "missing_requirements": [] if confirmed else ["explicit evidence"],
        "short_rationale": "trace",
        "confidence": "high" if confirmed else "low",
    }


def _event_result(doc_id: str, file_name: str, confirmed: bool, quote: str | None) -> str:
    return json.dumps(
        {
            "document_id": doc_id,
            "file_name": file_name,
            "fact_status": "подтверждено" if confirmed else "не подтверждено",
            "reasoning": "Есть прямое подтверждение выполнения." if confirmed else "Документ не содержит прямого факта.",
            "matched_action": "Построить" if confirmed else None,
            "matched_subject": "спортивный объект" if confirmed else None,
            "completion_signal": "введен в эксплуатацию" if confirmed else None,
            "observed_value": 2 if confirmed else None,
            "observed_unit": "ед" if confirmed else None,
            "comparison_result": "meets_target" if confirmed else "insufficient_data",
            "evidence_quote": quote,
            "reasoning_trace": _reasoning_trace(confirmed, quote),
        }
    )


def _phr_result(doc_id: str, file_name: str, confirmed: bool, quote: str | None) -> str:
    return json.dumps(
        {
            "document_id": doc_id,
            "file_name": file_name,
            "phr_fact_status": "подтверждено" if confirmed else "не подтверждено",
            "reasoning": "Показатель достигнут." if confirmed else "Нет нужного показателя.",
            "metric_matched": "Количество введенных объектов" if confirmed else None,
            "characteristic_explicitly_matched": confirmed,
            "quantity_refers_to_metric_object": confirmed,
            "observed_value": 2 if confirmed else None,
            "observed_unit": "ед" if confirmed else None,
            "comparison_result": "meets_target" if confirmed else "insufficient_data",
            "evidence_quote": quote,
            "reasoning_trace": _reasoning_trace(confirmed, quote),
        }
    )
