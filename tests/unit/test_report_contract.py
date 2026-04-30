from buratino.models.contracts import VerificationReport


def test_verification_report_contract_stable_keys() -> None:
    report = VerificationReport(
        event_id=1,
        event_name="event",
        event_type="qualitative",
        event_fact_status="не подтверждено",
        phr_fact_status="не указано",
        event_primary_file=None,
        phr_primary_file=None,
        logic_is_valid=True,
        primary_model="primary",
        audit_model="audit",
        event_reasoning="none",
        phr_reasoning="none",
    )

    assert set(report.to_dict()) == {
        "event_id",
        "event_name",
        "event_type",
        "event_fact_status",
        "phr_fact_status",
        "event_primary_file",
        "phr_primary_file",
        "logic_is_valid",
        "primary_model",
        "audit_model",
        "event_reasoning",
        "phr_reasoning",
        "detected_errors",
        "event_documents",
        "phr_documents",
        "supporting_files",
        "audit_reasoning",
        "primary_logic_is_valid",
        "primary_audit_reasoning",
        "audit_rerun_performed",
        "audit_rerun_event_documents",
        "audit_rerun_phr_documents",
        "audit_rerun_event_status",
        "audit_rerun_phr_status",
        "audit_rerun_logic_is_valid",
        "audit_rerun_reasoning",
        "confirming_documents_relation",
    }
