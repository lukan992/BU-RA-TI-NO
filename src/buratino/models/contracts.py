"""Machine-readable output contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from buratino.models.domain import ComparisonResult, DeadlineStatus, EventType, PhrVerdict, RelationStatus, Verdict

TraceConfidence = Literal["low", "medium", "high"]
RelationToEvent = Literal["direct", "indirect", "none", "unclear"]
RelationDateStatus = Literal["inside_period", "outside_period", "no_date", "unclear"]
AuditDecision = Literal["pass", "flip", "error"]


@dataclass(frozen=True)
class EvidenceItem:
    quote: str
    page: int | None
    source: str
    why_relevant: str


@dataclass(frozen=True)
class ReasoningTrace:
    reason_codes: list[str] = field(default_factory=list)
    evidence_items: list[EvidenceItem] = field(default_factory=list)
    missing_requirements: list[str] = field(default_factory=list)
    short_rationale: str = ""
    confidence: TraceConfidence = "low"


@dataclass(frozen=True)
class RelationDateCheck:
    status: RelationDateStatus
    document_dates: list[str] = field(default_factory=list)
    event_period: dict[str, str | None] = field(default_factory=dict)
    short_reason: str = ""


@dataclass(frozen=True)
class RelationMatrixItem:
    doc_id: str | None
    file_name: str
    relation_to_event: RelationToEvent
    relation_reason: str
    date_check: RelationDateCheck
    allowed_as_supporting_file: bool


@dataclass(frozen=True)
class AuditRuleViolation:
    rule: str
    affected_field: str
    from_value: str
    to_value: str
    reason: str


@dataclass(frozen=True)
class EvidenceTrace:
    event_fact: list[dict[str, Any]] = field(default_factory=list)
    phr_fact: list[dict[str, Any]] = field(default_factory=list)
    relation_checks: list[RelationMatrixItem] = field(default_factory=list)
    audit_rule_violations: list[AuditRuleViolation] = field(default_factory=list)


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
    reasoning_trace: ReasoningTrace = field(default_factory=ReasoningTrace)


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
    reasoning_trace: ReasoningTrace = field(default_factory=ReasoningTrace)


@dataclass(frozen=True)
class RankedDocument:
    document_id: str | None
    file_name: str
    rank: int
    reasoning: str
    score: int = 0
    reason_codes: list[str] = field(default_factory=list)
    short_reason: str = ""


@dataclass(frozen=True)
class RelationLlmResult:
    documents: list[dict[str, str | None]] = field(default_factory=list)


@dataclass(frozen=True)
class DocumentDateCheck:
    document_id: str | None
    file_name: str
    date_final_text: str | None
    document_date: str | None
    implementation_deadline: str | None
    within_implementation_deadline: DeadlineStatus
    date_reasoning: str


@dataclass(frozen=True)
class ConfirmingDocumentsRelation:
    event_id: int
    file_ids: str
    file_names: str
    reasoning: str
    relation_status: RelationStatus
    implementation_deadline: str | None
    confirming_documents_within_deadline_status: DeadlineStatus
    document_date_checks: list[DocumentDateCheck] = field(default_factory=list)
    relation_matrix: list[RelationMatrixItem] = field(default_factory=list)


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
    audit_result: AuditDecision = "pass"
    rule_violations: list[AuditRuleViolation] = field(default_factory=list)
    final_supporting_files: list[str] = field(default_factory=list)


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
    confirming_documents_relation: ConfirmingDocumentsRelation | None = None
    evidence_trace: EvidenceTrace = field(default_factory=EvidenceTrace)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
