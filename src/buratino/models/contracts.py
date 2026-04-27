"""Machine-readable output contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from buratino.models.domain import ComparisonResult, EventType, PhrVerdict, Verdict


@dataclass(frozen=True)
class DocumentFactResult:
    document_id: str | None
    file_name: str
    fact_status: Verdict
    reasoning: str
    matched_action: str | None = None
    matched_subject: str | None = None
    completion_signal: str | None = None
    observed_value: float | str | None = None
    observed_unit: str | None = None
    comparison_result: ComparisonResult = "insufficient_data"
    evidence_quote: str | None = None


@dataclass(frozen=True)
class DocumentPhrResult:
    document_id: str | None
    file_name: str
    phr_fact_status: Verdict
    reasoning: str
    metric_matched: str | None = None
    characteristic_explicitly_matched: bool = False
    quantity_refers_to_metric_object: bool = False
    observed_value: float | str | None = None
    observed_unit: str | None = None
    comparison_result: ComparisonResult = "insufficient_data"
    evidence_quote: str | None = None


@dataclass(frozen=True)
class AggregatedVerdict:
    status: PhrVerdict
    primary_file: str | None
    reasoning: str
    supporting_files: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AuditResult:
    logic_is_valid: bool
    detected_errors: list[str]
    corrected_event_status: Verdict
    corrected_phr_status: PhrVerdict
    corrected_reasoning: str


@dataclass(frozen=True)
class VerificationReport:
    event_id: int
    event_name: str
    event_type: EventType | None
    event_fact_status: Verdict
    phr_fact_status: PhrVerdict
    event_primary_file: str | None
    phr_primary_file: str | None
    logic_is_valid: bool
    primary_model: str
    audit_model: str
    event_reasoning: str
    phr_reasoning: str
    detected_errors: list[str] = field(default_factory=list)
    event_documents: list[DocumentFactResult] = field(default_factory=list)
    phr_documents: list[DocumentPhrResult] = field(default_factory=list)
    supporting_files: list[str] = field(default_factory=list)
    audit_reasoning: str | None = None
    primary_logic_is_valid: bool | None = None
    primary_audit_reasoning: str | None = None
    audit_rerun_performed: bool = False
    audit_rerun_event_documents: list[DocumentFactResult] = field(default_factory=list)
    audit_rerun_phr_documents: list[DocumentPhrResult] = field(default_factory=list)
    audit_rerun_event_status: Verdict | None = None
    audit_rerun_phr_status: Verdict | None = None
    audit_rerun_logic_is_valid: bool | None = None
    audit_rerun_reasoning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
