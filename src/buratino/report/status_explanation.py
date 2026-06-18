"""Short end-user explanations for final verification statuses."""

from __future__ import annotations

from dataclasses import dataclass

from buratino.models.contracts import (
    ConfirmingDocumentsRelation,
    DocumentFactResult,
    DocumentPhrResult,
    EvidenceItem,
    RelationMatrixItem,
)
from buratino.models.domain import PhrTarget, VerificationTarget

FORBIDDEN_TERMS = (
    "chunk",
    "ocr chunk",
    "doc-level",
    "audit",
    "aggregation",
    "fallback",
    "json",
    "model",
    "evidence_trace",
    "observed_quantity",
    "found_signals",
    "missing_requirements",
    "reason_codes",
)

HUMANIZED_REQUIREMENTS = {
    "observed_quantity": "количество, подтверждающее выполнение планового показателя",
    "observed_value": "количество, подтверждающее выполнение планового показателя",
    "фактическое значение": "количество, подтверждающее выполнение планового показателя",
    "unit": "единица измерения количества",
    "observed_unit": "единица измерения количества",
    "единица измерения": "единица измерения количества",
    "explicit evidence": "прямое подтверждение выполнения мероприятия",
    "explicit confirmation": "прямое подтверждение выполнения мероприятия",
    "прямой признак завершения": "прямое подтверждение выполнения мероприятия",
    "достаточное значение показателя": "значение показателя, которое подтверждает выполнение требования в полном объеме",
    "reason_codes": "прямое подтверждение выполнения требования",
    "missing_requirements": "прямое подтверждение выполнения требования",
    "found_signals": "прямое подтверждение выполнения требования",
}


@dataclass(frozen=True)
class ExplanationPayload:
    status: str
    target_type: str
    event_requirement: str
    used_documents: list[str]
    evidence_items: list[EvidenceItem]
    found_signals: list[str]
    missing_requirements: list[str]
    relation_check: str | None
    date_check: str | None
    decision_rule: str


def build_event_explanation(
    *,
    status: str,
    target: VerificationTarget,
    results: list[DocumentFactResult],
    final_supporting_files: list[str],
    relation: ConfirmingDocumentsRelation | None,
) -> str:
    reference_result = _select_event_reference_result(
        results=results,
        final_supporting_files=final_supporting_files,
    )
    relation_item = _relation_item_for_file(relation, reference_result.file_name if reference_result is not None else None)
    payload = ExplanationPayload(
        status=status,
        target_type="факт выполнения мероприятия",
        event_requirement=_build_event_requirement(target),
        used_documents=[reference_result.file_name] if reference_result is not None else [],
        evidence_items=[] if reference_result is None else reference_result.reasoning_trace.evidence_items,
        found_signals=[] if reference_result is None else _build_event_found_signals(reference_result),
        missing_requirements=[] if reference_result is None else _event_missing_requirements(target, reference_result),
        relation_check=None if relation_item is None else relation_item.relation_reason,
        date_check=None if relation_item is None else relation_item.date_check.short_reason,
        decision_rule=(
            "Статус подтверждается только при прямом подтверждении выполнения мероприятия."
            if status == "подтверждено"
            else "Без явного подтверждения выполнения статус не может быть положительным."
        ),
    )
    return format_status_explanation(payload, target=target, event_result=reference_result)


def build_phr_explanation(
    *,
    status: str,
    target: PhrTarget | None,
    results: list[DocumentPhrResult],
    final_supporting_files: list[str],
    phr_auto_confirmed: bool,
) -> str:
    if target is None:
        return (
            "Для этого мероприятия ПХР в исходных данных не задан. "
            "Поэтому отдельная проверка факта выполнения ПХР не проводилась. "
            "Статус по ПХР установлен как «не указано»."
        )
    if phr_auto_confirmed:
        return (
            f"Для ПХР «{target.phr_name}» требуемое значение равно 0. "
            "Это означает, что дополнительное подтверждение достижения показателя не требуется. "
            "Поэтому статус установлен как «подтверждено»."
        )

    reference_result = _select_phr_reference_result(
        results=results,
        final_supporting_files=final_supporting_files,
    )
    payload = ExplanationPayload(
        status=status,
        target_type="факт выполнения ПХР",
        event_requirement=_build_phr_requirement(target),
        used_documents=[reference_result.file_name] if reference_result is not None else [],
        evidence_items=[] if reference_result is None else reference_result.reasoning_trace.evidence_items,
        found_signals=[] if reference_result is None else _build_phr_found_signals(reference_result),
        missing_requirements=[] if reference_result is None else _phr_missing_requirements(target, reference_result),
        relation_check=None,
        date_check=None,
        decision_rule=(
            "Статус подтверждается только при прямом подтверждении значения ПХР."
            if status == "подтверждено"
            else "Без полного набора обязательных признаков статус ПХР не может быть положительным."
        ),
    )
    return format_status_explanation(payload, phr_target=target, phr_result=reference_result)


def format_status_explanation(
    payload: ExplanationPayload,
    *,
    target: VerificationTarget | None = None,
    event_result: DocumentFactResult | None = None,
    phr_target: PhrTarget | None = None,
    phr_result: DocumentPhrResult | None = None,
) -> str:
    if payload.status == "подтверждено":
        return _format_positive(payload)
    if target is not None:
        return _format_negative_event(payload, target=target, result=event_result)
    return _format_negative_phr(payload, target=phr_target, result=phr_result)


def _format_positive(payload: ExplanationPayload) -> str:
    document_sentence = (
        f'Статус «подтверждено» по проверке "{payload.target_type}" установлен на основании документа '
        f'«{payload.used_documents[0]}».'
        if payload.used_documents
        else f'Статус «подтверждено» по проверке "{payload.target_type}" установлен на основании значимого документа.'
    )
    quote_sentence = (
        f'Прямое подтверждение содержится во фрагменте: «{_clean_quote(payload.evidence_items[0].quote)}».'
        if payload.evidence_items
        else "В значимом документе есть прямое подтверждение выполнения требования."
    )
    requirement_sentence = f"Этот фрагмент подтверждает требование: {payload.event_requirement}."
    rule_sentence = "Поэтому статус установлен как «подтверждено»."
    return _sanitize(" ".join([document_sentence, quote_sentence, requirement_sentence, rule_sentence]))


def _format_negative_event(
    payload: ExplanationPayload,
    *,
    target: VerificationTarget,
    result: DocumentFactResult | None,
) -> str:
    document_part = _negative_event_document_sentence(payload, result=result)
    if payload.relation_check or payload.date_check:
        insufficiency_part = _negative_relation_or_date_sentence(payload)
        missing_part = _negative_event_missing_sentence(payload, target=target, result=result)
        final_part = "Поскольку явного подтверждения нет, статус установлен как «не подтверждено»."
        return _sanitize(" ".join([document_part, insufficiency_part, missing_part, final_part]))

    if target.event_type == "quantitative":
        return _sanitize(
            " ".join(
                [
                    document_part,
                    _negative_quantitative_event_sentence(target, result),
                    _negative_single_object_sentence(result),
                    _negative_quantitative_final_sentence(target, result),
                ]
            )
        )

    insufficiency_part = _negative_humanized_signals_sentence(payload, is_event=True)
    missing_part = _negative_event_missing_sentence(payload, target=target, result=result)
    final_part = "Поскольку явного подтверждения нет, статус установлен как «не подтверждено»."
    return _sanitize(" ".join([document_part, insufficiency_part, missing_part, final_part]))


def _format_negative_phr(
    payload: ExplanationPayload,
    *,
    target: PhrTarget | None,
    result: DocumentPhrResult | None,
) -> str:
    document_part = _negative_phr_document_sentence(payload)
    insufficiency_part = _negative_humanized_signals_sentence(payload, is_event=False)
    missing_part = _negative_phr_missing_sentence(payload, target=target, result=result)
    final_part = "Поскольку явного подтверждения нет, статус установлен как «не подтверждено»."
    return _sanitize(" ".join([document_part, insufficiency_part, missing_part, final_part]))


def _negative_event_document_sentence(payload: ExplanationPayload, *, result: DocumentFactResult | None) -> str:
    if payload.used_documents and result is not None:
        if result.matched_subject:
            return (
                f'Документ «{payload.used_documents[0]}» подтверждает наличие объекта '
                f'«{_clean_quote(result.matched_subject)}», связанного с мероприятием.'
            )
        if payload.evidence_items:
            return (
                f'Документ «{payload.used_documents[0]}» содержит сведения: '
                f'«{_clean_quote(payload.evidence_items[0].quote)}».'
            )
    if payload.used_documents:
        return f'Документ «{payload.used_documents[0]}» содержит сведения по требованию: {payload.event_requirement}.'
    return f"Проверенные значимые документы содержат сведения по требованию: {payload.event_requirement}."


def _negative_phr_document_sentence(payload: ExplanationPayload) -> str:
    if payload.used_documents and payload.evidence_items:
        return (
            f'Документ «{payload.used_documents[0]}» содержит сведения: '
            f'«{_clean_quote(payload.evidence_items[0].quote)}».'
        )
    if payload.used_documents:
        return f'Документ «{payload.used_documents[0]}» содержит сведения по требованию: {payload.event_requirement}.'
    return f"Проверенные значимые документы содержат сведения по требованию: {payload.event_requirement}."


def _negative_relation_or_date_sentence(payload: ExplanationPayload) -> str:
    reasons: list[str] = []
    if payload.relation_check:
        reasons.append(payload.relation_check.lower().rstrip("."))
    if payload.date_check:
        reasons.append(payload.date_check.lower().rstrip("."))
    return f"Однако этого недостаточно, потому что {' и '.join(reasons)}."


def _negative_quantitative_event_sentence(
    target: VerificationTarget,
    result: DocumentFactResult | None,
) -> str:
    planned_value = _format_number(target.planned_value)
    planned_unit = _format_count_unit(target.planned_unit, target.planned_value)
    if result is not None and result.observed_value is not None:
        observed_value = _format_number(result.observed_value)
        observed_unit = _format_count_unit(result.observed_unit or target.planned_unit, result.observed_value)
        return (
            "Однако этого недостаточно для подтверждения выполнения мероприятия, потому что "
            f"плановый показатель составляет {planned_value} {planned_unit}, "
            f"а в документе указано {observed_value} {observed_unit}."
        )
    return (
        "Однако этого недостаточно для подтверждения выполнения мероприятия, потому что "
        f"плановый показатель составляет {planned_value} {planned_unit}, "
        f"а в документе не указано, что приобретено {planned_value} {planned_unit}."
    )


def _negative_single_object_sentence(result: DocumentFactResult | None) -> str:
    if result is None:
        return "Документ не подтверждает выполнение количественного показателя в полном объеме."
    if result.matched_subject or result.reasoning_trace.evidence_items:
        return (
            "Документ подтверждает наличие отдельного объекта, "
            "но не подтверждает выполнение количественного показателя в полном объеме."
        )
    return "Документ не подтверждает выполнение количественного показателя в полном объеме."


def _negative_quantitative_final_sentence(
    target: VerificationTarget,
    result: DocumentFactResult | None,
) -> str:
    if result is not None and result.observed_value is None:
        return "Поскольку явного подтверждения количества нет, статус установлен как «не подтверждено»."
    return "Поскольку количественный показатель не подтвержден в полном объеме, статус установлен как «не подтверждено»."


def _negative_humanized_signals_sentence(payload: ExplanationPayload, *, is_event: bool) -> str:
    if payload.found_signals:
        return (
            "Однако этого недостаточно, потому что "
            f"{_humanize_signals(payload.found_signals, is_event=is_event)}."
        )
    return "Однако этого недостаточно для прямого подтверждения выполнения."


def _negative_event_missing_sentence(
    payload: ExplanationPayload,
    *,
    target: VerificationTarget,
    result: DocumentFactResult | None,
) -> str:
    humanized_missing = _humanize_missing_requirements(payload.missing_requirements)
    if humanized_missing:
        return f"Не хватает {humanized_missing[0]}."
    if target.event_type == "quantitative" and result is not None and result.observed_value is None:
        planned_value = _format_number(target.planned_value)
        planned_unit = _format_count_unit(target.planned_unit, target.planned_value)
        return f"Не хватает прямого указания на то, что приобретено {planned_value} {planned_unit}."
    return "Не хватает прямого подтверждения выполнения мероприятия."


def _negative_phr_missing_sentence(
    payload: ExplanationPayload,
    *,
    target: PhrTarget | None,
    result: DocumentPhrResult | None,
) -> str:
    humanized_missing = _humanize_missing_requirements(payload.missing_requirements)
    if humanized_missing:
        return f"Не хватает {humanized_missing[0]}."
    if target is not None and result is not None and result.comparison_result != "meets_target":
        planned_value = _format_number(target.phr_value_2025)
        unit = _format_count_unit(target.phr_unit, target.phr_value_2025)
        return f"Не хватает подтверждения того, что показатель достиг значения {planned_value} {unit}."
    return "Не хватает прямого подтверждения выполнения показателя."


def _build_event_requirement(target: VerificationTarget) -> str:
    requirement = target.event_name
    if target.event_type == "quantitative" and target.planned_value is not None:
        unit = f" {target.planned_unit}" if target.planned_unit else ""
        requirement += f", целевое значение {target.planned_value}{unit}"
    return requirement


def _build_phr_requirement(target: PhrTarget) -> str:
    requirement = target.phr_name
    if target.phr_value_2025 is not None:
        unit = f" {target.phr_unit}" if target.phr_unit else ""
        requirement += f", требуемое значение {target.phr_value_2025}{unit}"
    return requirement


def _select_event_reference_result(
    *,
    results: list[DocumentFactResult],
    final_supporting_files: list[str],
) -> DocumentFactResult | None:
    for result in results:
        if result.file_name in final_supporting_files and result.reasoning_trace.evidence_items:
            return result
    for result in results:
        if result.reasoning_trace.evidence_items:
            return result
    for result in results:
        if _build_event_found_signals(result):
            return result
    return results[0] if results else None


def _select_phr_reference_result(
    *,
    results: list[DocumentPhrResult],
    final_supporting_files: list[str],
) -> DocumentPhrResult | None:
    for result in results:
        if result.file_name in final_supporting_files and result.reasoning_trace.evidence_items:
            return result
    for result in results:
        if result.reasoning_trace.evidence_items:
            return result
    for result in results:
        if _build_phr_found_signals(result):
            return result
    return results[0] if results else None


def _build_event_found_signals(result: DocumentFactResult) -> list[str]:
    signals: list[str] = []
    if result.matched_action:
        signals.append(f"документ связывает объект с действием «{result.matched_action}»")
    if result.matched_subject:
        signals.append(f"документ упоминает объект «{result.matched_subject}»")
    if result.completion_signal:
        signals.append("в документе есть сведения, связанные с мероприятием")
    if result.observed_value is not None:
        value = f"{_format_number(result.observed_value)}"
        if result.observed_unit:
            value = f"{value} {_format_count_unit(result.observed_unit, result.observed_value)}"
        signals.append(f"в документе указано количество {value}")
    return signals


def _build_phr_found_signals(result: DocumentPhrResult) -> list[str]:
    signals: list[str] = []
    if result.metric_matched:
        signals.append(f"документ содержит сведения по показателю «{result.metric_matched}»")
    if result.characteristic_explicitly_matched:
        signals.append("в документе есть нужная характеристика объекта")
    if result.quantity_refers_to_metric_object:
        signals.append("количество относится к нужному объекту")
    if result.observed_value is not None:
        value = f"{_format_number(result.observed_value)}"
        if result.observed_unit:
            value = f"{value} {_format_count_unit(result.observed_unit, result.observed_value)}"
        signals.append(f"в документе указано значение {value}")
    return signals


def _event_missing_requirements(target: VerificationTarget, result: DocumentFactResult) -> list[str]:
    missing = list(result.reasoning_trace.missing_requirements)
    if not missing:
        if not result.matched_action:
            missing.append("действие по мероприятию")
        if not result.matched_subject:
            missing.append("объект мероприятия")
        if not result.completion_signal:
            missing.append("прямое подтверждение выполнения мероприятия")
        if target.event_type == "quantitative":
            if result.observed_value is None:
                missing.append("количество, подтверждающее выполнение планового показателя")
            if not result.observed_unit:
                missing.append("единица измерения количества")
    return missing


def _phr_missing_requirements(target: PhrTarget, result: DocumentPhrResult) -> list[str]:
    missing = list(result.reasoning_trace.missing_requirements)
    if not missing:
        if not result.metric_matched:
            missing.append(f"метрика «{target.phr_name}»")
        if not result.characteristic_explicitly_matched:
            missing.append("явное указание нужной характеристики")
        if not result.quantity_refers_to_metric_object:
            missing.append("связь количества с нужным объектом")
        if result.observed_value is None:
            missing.append("количество, подтверждающее выполнение планового показателя")
        if not result.observed_unit:
            missing.append("единица измерения количества")
        if result.comparison_result != "meets_target":
            missing.append("значение показателя, которое подтверждает выполнение требования в полном объеме")
    return missing


def _relation_item_for_file(
    relation: ConfirmingDocumentsRelation | None,
    file_name: str | None,
) -> RelationMatrixItem | None:
    if relation is None or file_name is None:
        return None
    for item in relation.relation_matrix:
        if item.file_name == file_name:
            return item
    return None


def _humanize_missing_requirements(items: list[str]) -> list[str]:
    return [_humanize_requirement(item) for item in items]


def _humanize_requirement(value: str) -> str:
    cleaned = value.strip()
    lowered = cleaned.lower()
    for key, humanized in HUMANIZED_REQUIREMENTS.items():
        if key in lowered:
            return humanized
    if "_" not in cleaned and cleaned == lowered:
        return cleaned
    if "_" not in cleaned and any("а" <= char <= "я" or char == "ё" for char in lowered):
        return cleaned
    return "прямое подтверждение выполнения требования"


def _humanize_signals(signals: list[str], *, is_event: bool) -> str:
    cleaned = [_clean_quote(signal) for signal in signals]
    if is_event:
        return ", ".join(cleaned)
    return ", ".join(cleaned)


def _clean_quote(text: str) -> str:
    return " ".join(text.split())


def _format_number(value: float | int | None) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _format_count_unit(unit: str | None, value: float | int | None) -> str:
    if unit is None:
        return "единиц"
    normalized = unit.strip().lower()
    if normalized in {"единица", "единицы", "ед", "шт", "штука", "штук"}:
        return "единиц"
    return unit.strip()


def _sanitize(text: str) -> str:
    sanitized = " ".join(text.split())
    lowered = sanitized.lower()
    for term in FORBIDDEN_TERMS:
        if term in lowered:
            raise ValueError(f"Forbidden term in explanation: {term}")
    return sanitized
