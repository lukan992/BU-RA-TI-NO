"""Helpers for mapping internal verifier results to the worker contract."""

from __future__ import annotations

from dataclasses import asdict

from buratino.models.contracts import DocumentFactResult, DocumentPhrResult
from buratino.models.domain import VerificationTarget
from buratino.models.result_contract import BusinessStatus, EvidenceItemEntry, SupportingFileEntry


def lower_verdict_to_business_status(value: str, *, not_applicable: bool = False) -> BusinessStatus:
    if not_applicable:
        return "Не применимо"
    if value == "подтверждено":
        return "Подтверждено"
    if value == "не подтверждено":
        return "Не подтверждено"
    if value == "не указано":
        return "Не применимо"
    return "Не проверялось"


def plan_check_applies(target: VerificationTarget) -> bool:
    """Plan check applies whenever xlsx provides a positive planned value.

    Applicability is driven by ``planned_value`` from xlsx_events, not by the
    LLM-resolved ``event_type``: a present positive planned value means the plan
    must be verified, so ``plan_status`` can never be "Не применимо" in that case.
    """

    return target.planned_value is not None and target.planned_value > 0


def quantitative_event_is_confirmed(result: DocumentFactResult, target: VerificationTarget) -> bool:
    semantically_confirmed = result.fact_status == "подтверждено" and bool(
        result.reasoning_trace.evidence_items
    )
    if not plan_check_applies(target):
        return semantically_confirmed
    if target.planned_value is not None and target.planned_value <= 1:
        # Single-unit plan (e.g. planned_value=1): OCR confirming that the
        # result/object was created or the event happened == achieving 1 unit.
        return semantically_confirmed
    return (
        semantically_confirmed
        and result.comparison_result == "meets_target"
        and result.observed_value is not None
        and bool(result.observed_unit)
    )


def build_supporting_file_entry(
    *,
    document_id: str | None,
    filename: str,
    reason: str,
) -> SupportingFileEntry:
    return SupportingFileEntry(document_id=document_id, filename=filename, reason=reason)


def build_evidence_items_for_event(
    result: DocumentFactResult,
    *,
    include_plan: bool,
) -> list[EvidenceItemEntry]:
    supports = ["event_description", "plan"] if include_plan else ["event_description"]
    entries: list[EvidenceItemEntry] = []
    for index, item in enumerate(result.reasoning_trace.evidence_items, start=1):
        entries.append(
            EvidenceItemEntry(
                document_id=result.document_id,
                filename=result.file_name,
                page_number=item.page,
                chunk_id=_build_chunk_id(result.document_id, index),
                text_fragment=item.quote,
                supports=supports,
            )
        )
    return entries


def build_evidence_items_for_phr(result: DocumentPhrResult) -> list[EvidenceItemEntry]:
    entries: list[EvidenceItemEntry] = []
    for index, item in enumerate(result.reasoning_trace.evidence_items, start=1):
        entries.append(
            EvidenceItemEntry(
                document_id=result.document_id,
                filename=result.file_name,
                page_number=item.page,
                chunk_id=_build_chunk_id(result.document_id, index),
                text_fragment=item.quote,
                supports=["phr"],
            )
        )
    return entries


def stringify_expected_plan(target: VerificationTarget) -> str | None:
    if target.planned_value is None:
        return None
    if target.planned_unit:
        return f"{target.planned_value:g} {target.planned_unit}"
    return f"{target.planned_value:g}"


def stringify_observed_plan(result: DocumentFactResult | None) -> str | None:
    if result is None or result.observed_value is None:
        return None
    if result.observed_unit:
        return f"{result.observed_value} {result.observed_unit}"
    return str(result.observed_value)


def summarize_supporting_reason(result: DocumentFactResult | DocumentPhrResult) -> str:
    if result.reasoning_trace.short_rationale:
        return result.reasoning_trace.short_rationale
    return result.reasoning


def _build_chunk_id(document_id: str | None, index: int) -> str | None:
    if document_id is None:
        return None
    return f"{document_id}:chunk-{index}"


def dataclass_list_to_json(items: list[object]) -> list[dict]:
    return [asdict(item) for item in items]
