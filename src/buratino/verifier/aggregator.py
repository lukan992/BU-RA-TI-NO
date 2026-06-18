"""Aggregation helpers with fail-closed policy."""

from __future__ import annotations

from collections.abc import Iterable

from buratino.models.contracts import AggregatedVerdict, DocumentFactResult, DocumentPhrResult

CONFIRMED = "подтверждено"
NOT_CONFIRMED = "не подтверждено"


def aggregate_event_results(results: list[DocumentFactResult]) -> AggregatedVerdict:
    confirmed = select_event_supporting_results(results)
    if not confirmed:
        return AggregatedVerdict(
            status=NOT_CONFIRMED,
            primary_file=None,
            reasoning="Явного подтверждения по evidence не найдено.",
            supporting_files=[],
        )

    primary = confirmed[0]
    supporting_files = _unique_files(result.file_name for result in confirmed)
    return AggregatedVerdict(
        status=CONFIRMED,
        primary_file=primary.file_name,
        reasoning=primary.reasoning,
        supporting_files=supporting_files,
    )


def aggregate_phr_results(results: list[DocumentPhrResult]) -> AggregatedVerdict:
    confirmed = select_phr_supporting_results(results)
    if not confirmed:
        return AggregatedVerdict(
            status=NOT_CONFIRMED,
            primary_file=None,
            reasoning="Явного подтверждения ПХР по evidence не найдено.",
            supporting_files=[],
        )

    primary = confirmed[0]
    supporting_files = _unique_files(result.file_name for result in confirmed)
    return AggregatedVerdict(
        status=CONFIRMED,
        primary_file=primary.file_name,
        reasoning=primary.reasoning,
        supporting_files=supporting_files,
    )


def select_event_supporting_results(results: list[DocumentFactResult]) -> list[DocumentFactResult]:
    return [result for result in results if _is_confirmed_event_result(result)]


def select_phr_supporting_results(results: list[DocumentPhrResult]) -> list[DocumentPhrResult]:
    return [result for result in results if _is_confirmed_phr_result(result)]


def _unique_files(file_names: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for file_name in file_names:
        if file_name not in seen:
            seen.add(file_name)
            ordered.append(file_name)
    return ordered


def _is_confirmed_phr_result(result: DocumentPhrResult) -> bool:
    return (
        result.phr_fact_status == CONFIRMED
        and bool(result.reasoning_trace.evidence_items)
        and bool(result.metric_matched)
        and result.characteristic_explicitly_matched
        and result.quantity_refers_to_metric_object
        and result.observed_value is not None
        and bool(result.observed_unit)
        and result.comparison_result == "meets_target"
    )


def _is_confirmed_event_result(result: DocumentFactResult) -> bool:
    return result.fact_status == CONFIRMED and bool(result.reasoning_trace.evidence_items)
