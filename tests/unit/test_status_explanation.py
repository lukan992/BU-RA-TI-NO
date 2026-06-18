from __future__ import annotations

from buratino.models.contracts import (
    ConfirmingDocumentsRelation,
    DocumentDateCheck,
    DocumentFactResult,
    DocumentPhrResult,
    EvidenceItem,
    ReasoningTrace,
    RelationDateCheck,
    RelationMatrixItem,
)
from buratino.models.domain import PhrTarget, VerificationTarget
from buratino.report.status_explanation import build_event_explanation, build_phr_explanation


def _trace(quote: str | None, missing: list[str] | None = None) -> ReasoningTrace:
    return ReasoningTrace(
        reason_codes=["mentions_completion_fact"] if quote else ["insufficient_evidence"],
        evidence_items=(
            [EvidenceItem(quote=quote, page=None, source="summary", why_relevant="Прямое подтверждение.")]
            if quote
            else []
        ),
        missing_requirements=missing or ([] if quote else ["прямой признак завершения"]),
        short_rationale="Короткое объяснение.",
        confidence="high" if quote else "low",
    )


def test_event_explanation_for_confirmed_status_mentions_only_significant_document() -> None:
    text = build_event_explanation(
        status="подтверждено",
        target=VerificationTarget(
            event_id=1,
            event_name="Построить спортивный объект",
            event_description="Описание",
            event_type="qualitative",
            normalized_action="построить",
            normalized_subject="спортивный объект",
            planned_value=0,
            planned_unit="шт",
        ),
        results=[
            DocumentFactResult(
                document_id="1",
                file_name="report.pdf",
                fact_status="подтверждено",
                reasoning="internal",
                completion_signal="выполнено",
                reasoning_trace=_trace("мероприятие выполнено"),
            )
        ],
        final_supporting_files=["report.pdf"],
        relation=None,
    )

    assert "report.pdf" in text
    assert "мероприятие выполнено" in text
    assert "подтверждено" in text
    assert "Doc-level" not in text


def test_event_explanation_for_negative_status_uses_humanized_relation_reason() -> None:
    relation = ConfirmingDocumentsRelation(
        event_id=1,
        file_ids="1",
        file_names="report.pdf",
        reasoning="",
        relation_status="не относится",
        implementation_deadline="2025-12-31",
        confirming_documents_within_deadline_status="нет",
        document_date_checks=[
            DocumentDateCheck(
                document_id="1",
                file_name="report.pdf",
                date_final_text=None,
                document_date=None,
                implementation_deadline="2025-12-31",
                within_implementation_deadline="нет",
                date_reasoning="Дата документа позже срока реализации.",
            )
        ],
        relation_matrix=[
            RelationMatrixItem(
                doc_id="1",
                file_name="report.pdf",
                relation_to_event="none",
                relation_reason="Связь документа с мероприятием не подтверждена.",
                date_check=RelationDateCheck(
                    status="outside_period",
                    document_dates=["2026-01-10"],
                    event_period={"start": None, "end": "2025-12-31"},
                    short_reason="Дата документа позже срока реализации.",
                ),
                allowed_as_supporting_file=False,
            )
        ],
    )
    text = build_event_explanation(
        status="не подтверждено",
        target=VerificationTarget(
            event_id=1,
            event_name="Построить спортивный объект",
            event_description="Описание",
            event_type="quantitative",
            normalized_action="построить",
            normalized_subject="спортивный объект",
            planned_value=2,
            planned_unit="ед",
        ),
        results=[
            DocumentFactResult(
                document_id="1",
                file_name="report.pdf",
                fact_status="не подтверждено",
                reasoning="internal",
                observed_value=1,
                observed_unit="ед",
                reasoning_trace=_trace(None, ["фактическое значение не ниже целевого"]),
            )
        ],
        final_supporting_files=[],
        relation=relation,
    )

    assert "Однако этого недостаточно, потому что" in text
    assert "Связь документа с мероприятием не подтверждена".lower() in text.lower()
    assert "Поскольку явного подтверждения нет" in text
    assert "chunk" not in text.lower()


def test_event_explanation_for_quantitative_missing_count_is_human_readable() -> None:
    text = build_event_explanation(
        status="не подтверждено",
        target=VerificationTarget(
            event_id=1,
            event_name="Приобретение БАС для мониторинга",
            event_description="Описание",
            event_type="quantitative",
            normalized_action="приобрести",
            normalized_subject="беспилотная авиационная система Геоскан 801",
            planned_value=48,
            planned_unit="Единица",
        ),
        results=[
            DocumentFactResult(
                document_id="1",
                file_name="Подтверждающие сведения 1.pdf",
                fact_status="не подтверждено",
                reasoning="internal",
                matched_action="Приобретены отечественные беспилотные авиационные системы для рыбохозяйственной отрасли",
                matched_subject="Беспилотная авиационная система Геоскан 801",
                completion_signal="подтверждено",
                reasoning_trace=_trace(
                    "Наименование объекта (полное): Беспилотная авиационная система Геоскан 801",
                    ["observed_quantity"],
                ),
            )
        ],
        final_supporting_files=[],
        relation=None,
    )

    assert "Подтверждающие сведения 1.pdf" in text
    assert "плановый показатель составляет 48 единиц" in text
    assert "в документе не указано, что приобретено 48 единиц" in text
    assert "Документ подтверждает наличие отдельного объекта" in text
    assert "Поскольку явного подтверждения количества нет" in text


def test_explanations_do_not_expose_technical_keys() -> None:
    event_text = build_event_explanation(
        status="не подтверждено",
        target=VerificationTarget(
            event_id=1,
            event_name="Приобретение БАС",
            event_description="Описание",
            event_type="quantitative",
            normalized_action="приобрести",
            normalized_subject="БАС",
            planned_value=48,
            planned_unit="Единица",
        ),
        results=[
            DocumentFactResult(
                document_id="1",
                file_name="report.pdf",
                fact_status="не подтверждено",
                reasoning="internal",
                matched_subject="БАС Геоскан 801",
                completion_signal="подтверждено",
                reasoning_trace=_trace("БАС Геоскан 801", ["observed_quantity", "found_signals"]),
            )
        ],
        final_supporting_files=[],
        relation=None,
    )
    phr_text = build_phr_explanation(
        status="не подтверждено",
        target=PhrTarget(
            event_id=1,
            event_name="Событие",
            phr_name="Количество участников",
            phr_value_2025=10,
            phr_unit="чел",
        ),
        results=[
            DocumentPhrResult(
                document_id="1",
                file_name="report.pdf",
                phr_fact_status="не подтверждено",
                reasoning="internal",
                metric_matched="Количество участников",
                observed_value=5,
                observed_unit="чел",
                comparison_result="below_target",
                reasoning_trace=_trace("участвовали 5 человек", ["reason_codes", "missing_requirements"]),
            )
        ],
        final_supporting_files=[],
        phr_auto_confirmed=False,
    )

    forbidden = [
        "observed_quantity",
        "found_signals",
        "missing_requirements",
        "reason_codes",
        "chunk",
        "doc-level",
        "audit",
        "fallback",
        "json",
    ]
    for term in forbidden:
        assert term not in event_text.lower()
        assert term not in phr_text.lower()


def test_phr_explanation_for_missing_phr_is_user_friendly() -> None:
    text = build_phr_explanation(
        status="не указано",
        target=None,
        results=[],
        final_supporting_files=[],
        phr_auto_confirmed=False,
    )

    assert "ПХР" in text
    assert "не указано" in text
    assert "json" not in text.lower()


def test_phr_explanation_for_negative_status_mentions_humanized_missing_requirement() -> None:
    text = build_phr_explanation(
        status="не подтверждено",
        target=PhrTarget(
            event_id=1,
            event_name="Событие",
            phr_name="Количество участников",
            phr_value_2025=10,
            phr_unit="чел",
        ),
        results=[
            DocumentPhrResult(
                document_id="1",
                file_name="report.pdf",
                phr_fact_status="не подтверждено",
                reasoning="internal",
                metric_matched="Количество участников",
                observed_value=5,
                observed_unit="чел",
                comparison_result="below_target",
                reasoning_trace=_trace("участвовали 5 человек", ["достаточное значение показателя"]),
            )
        ],
        final_supporting_files=[],
        phr_auto_confirmed=False,
    )

    assert "report.pdf" in text
    assert "участвовали 5 человек" in text
    assert "значение показателя, которое подтверждает выполнение требования в полном объеме" in text
    assert "Поскольку явного подтверждения нет" in text
