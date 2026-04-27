"""Aggregation helpers with fail-closed policy."""

from __future__ import annotations

from buratino.models.contracts import AggregatedVerdict, DocumentFactResult, DocumentPhrResult

CONFIRMED = "подтверждено"
NOT_CONFIRMED = "не подтверждено"


def aggregate_event_results(results: list[DocumentFactResult]) -> AggregatedVerdict:
    confirmed = [result for result in results if result.fact_status == CONFIRMED]
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
    confirmed = [
        result
        for result in results
        if result.phr_fact_status == CONFIRMED
        and result.characteristic_explicitly_matched
        and result.quantity_refers_to_metric_object
    ]
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


def _unique_files(file_names: list[str] | tuple[str, ...] | object) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for file_name in file_names:
        if file_name not in seen:
            seen.add(file_name)
            ordered.append(file_name)
    return ordered
