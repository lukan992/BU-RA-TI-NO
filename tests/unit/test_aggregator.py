from buratino.models.contracts import DocumentFactResult, DocumentPhrResult
from buratino.verifier.aggregator import aggregate_event_results, aggregate_phr_results


def test_aggregator_is_fail_closed_without_confirmation() -> None:
    aggregated = aggregate_event_results(
        [
            DocumentFactResult(
                document_id="1",
                file_name="doc.pdf",
                fact_status="не подтверждено",
                reasoning="future plan only",
            )
        ]
    )

    assert aggregated.status == "не подтверждено"
    assert aggregated.primary_file is None


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
            )
        ]
    )

    assert aggregated.status == "не подтверждено"
    assert aggregated.primary_file is None
