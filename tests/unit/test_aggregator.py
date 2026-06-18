from buratino.models.contracts import DocumentFactResult, DocumentPhrResult, EvidenceItem, ReasoningTrace
from buratino.verifier.aggregator import aggregate_event_results, aggregate_phr_results


def _trace(*, quote: str | None = None) -> ReasoningTrace:
    evidence_items = []
    if quote is not None:
        evidence_items.append(
            EvidenceItem(
                quote=quote,
                page=None,
                source="summary",
                why_relevant="Direct confirmation.",
            )
        )
    return ReasoningTrace(
        reason_codes=["insufficient_evidence"] if quote is None else ["mentions_completion_fact"],
        evidence_items=evidence_items,
        missing_requirements=[] if quote is not None else ["explicit confirmation"],
        short_rationale="trace",
        confidence="high" if quote is not None else "low",
    )


def test_aggregator_is_fail_closed_without_confirmation() -> None:
    aggregated = aggregate_event_results(
        [
            DocumentFactResult(
                document_id="1",
                file_name="doc.pdf",
                fact_status="не подтверждено",
                reasoning="future plan only",
                reasoning_trace=_trace(),
            )
        ]
    )

    assert aggregated.status == "не подтверждено"
    assert aggregated.primary_file is None


def test_event_aggregator_collects_all_confirming_files_without_duplicates() -> None:
    aggregated = aggregate_event_results(
        [
            DocumentFactResult(
                document_id="1",
                file_name="contract.pdf",
                fact_status="подтверждено",
                reasoning="contract confirms scope",
                reasoning_trace=_trace(quote="contract confirms scope"),
            ),
            DocumentFactResult(
                document_id="2",
                file_name="act.pdf",
                fact_status="подтверждено",
                reasoning="act confirms acceptance",
                reasoning_trace=_trace(quote="act confirms acceptance"),
            ),
            DocumentFactResult(
                document_id="3",
                file_name="contract.pdf",
                fact_status="подтверждено",
                reasoning="duplicate file name should not repeat",
                reasoning_trace=_trace(quote="duplicate file name should not repeat"),
            ),
            DocumentFactResult(
                document_id="4",
                file_name="noise.pdf",
                fact_status="не подтверждено",
                reasoning="read but not used",
                reasoning_trace=_trace(),
            ),
        ]
    )

    assert aggregated.status == "подтверждено"
    assert aggregated.primary_file == "contract.pdf"
    assert aggregated.supporting_files == ["contract.pdf", "act.pdf"]


def test_phr_aggregator_confirms_when_characteristic_and_quantity_match() -> None:
    aggregated = aggregate_phr_results(
        [
            DocumentPhrResult(
                document_id="1",
                file_name="doc.pdf",
                phr_fact_status="подтверждено",
                reasoning="explicit characteristic and quantity",
                metric_matched="БАС мультироторного типа",
                characteristic_explicitly_matched=True,
                quantity_refers_to_metric_object=True,
                observed_value=20,
                observed_unit="шт",
                comparison_result="meets_target",
                evidence_quote="поставлено 20 БАС мультироторного типа",
                reasoning_trace=_trace(quote="поставлено 20 БАС мультироторного типа"),
            )
        ]
    )

    assert aggregated.status == "подтверждено"
    assert aggregated.primary_file == "doc.pdf"


def test_phr_aggregator_rejects_generic_object_without_characteristic() -> None:
    aggregated = aggregate_phr_results(
        [
            DocumentPhrResult(
                document_id="1",
                file_name="doc.pdf",
                phr_fact_status="подтверждено",
                reasoning="generic object only",
                metric_matched="БАС",
                characteristic_explicitly_matched=False,
                quantity_refers_to_metric_object=True,
                observed_value=50,
                observed_unit="шт",
                comparison_result="meets_target",
                evidence_quote="поставлено 50 БАС",
                reasoning_trace=_trace(quote="поставлено 50 БАС"),
            )
        ]
    )

    assert aggregated.status == "не подтверждено"
    assert aggregated.primary_file is None


def test_phr_aggregator_rejects_quantity_for_recipients_not_metric_object() -> None:
    aggregated = aggregate_phr_results(
        [
            DocumentPhrResult(
                document_id="1",
                file_name="doc.pdf",
                phr_fact_status="подтверждено",
                reasoning="quantity belongs to recipients",
                metric_matched="БАС мультироторного типа",
                characteristic_explicitly_matched=True,
                quantity_refers_to_metric_object=False,
                observed_value=20,
                observed_unit="шт",
                comparison_result="meets_target",
                evidence_quote="20 филиалов получили БАС мультироторного типа",
                reasoning_trace=_trace(quote="20 филиалов получили БАС мультироторного типа"),
            )
        ]
    )

    assert aggregated.status == "не подтверждено"
    assert aggregated.primary_file is None


def test_phr_aggregator_rejects_missing_unit_even_if_llm_marked_confirmed() -> None:
    aggregated = aggregate_phr_results(
        [
            DocumentPhrResult(
                document_id="1",
                file_name="doc.pdf",
                phr_fact_status="подтверждено",
                reasoning="unit is missing",
                metric_matched="Количество введенных объектов",
                characteristic_explicitly_matched=True,
                quantity_refers_to_metric_object=True,
                observed_value=2,
                observed_unit=None,
                comparison_result="meets_target",
                evidence_quote="введены 2 объекта",
                reasoning_trace=_trace(quote="введены 2 объекта"),
            )
        ]
    )

    assert aggregated.status == "не подтверждено"
    assert aggregated.primary_file is None


def test_phr_aggregator_rejects_below_target_even_if_llm_marked_confirmed() -> None:
    aggregated = aggregate_phr_results(
        [
            DocumentPhrResult(
                document_id="1",
                file_name="doc.pdf",
                phr_fact_status="подтверждено",
                reasoning="value is below target",
                metric_matched="Количество введенных объектов",
                characteristic_explicitly_matched=True,
                quantity_refers_to_metric_object=True,
                observed_value=1,
                observed_unit="ед",
                comparison_result="below_target",
                evidence_quote="введен 1 объект",
                reasoning_trace=_trace(quote="введен 1 объект"),
            )
        ]
    )

    assert aggregated.status == "не подтверждено"
    assert aggregated.primary_file is None


def test_event_aggregator_rejects_confirmed_verdict_without_evidence_items() -> None:
    aggregated = aggregate_event_results(
        [
            DocumentFactResult(
                document_id="1",
                file_name="doc.pdf",
                fact_status="подтверждено",
                reasoning="llm said confirmed",
                reasoning_trace=_trace(),
            )
        ]
    )

    assert aggregated.status == "не подтверждено"
    assert aggregated.primary_file is None
