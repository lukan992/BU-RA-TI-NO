"""Domain and output contracts for buratino."""

from buratino.models.contracts import (
    AggregatedVerdict,
    AuditResult,
    AuditRuleViolation,
    DocumentFactResult,
    DocumentPhrResult,
    EvidenceItem,
    EvidenceTrace,
    RankedDocument,
    ReasoningTrace,
    VerificationReport,
)
from buratino.models.domain import (
    ComparisonResult,
    DocumentSummary,
    EvidenceSource,
    EventRecord,
    EventType,
    PhrTarget,
    PhrRecord,
    PhrVerdict,
    VerificationTarget,
    Verdict,
)
from buratino.models.job import BuratinoAnalysisJob
from buratino.models.result_contract import BuratinoResult, validate_result_json
from buratino.models.errors import (
    BuratinoError,
    DataContractError,
    LlmOutputError,
    NotFoundError,
    RepositoryError,
    ValidationError,
)

__all__ = [
    "AggregatedVerdict",
    "AuditResult",
    "AuditRuleViolation",
    "BuratinoError",
    "BuratinoAnalysisJob",
    "BuratinoResult",
    "ComparisonResult",
    "DataContractError",
    "DocumentFactResult",
    "DocumentPhrResult",
    "DocumentSummary",
    "EvidenceItem",
    "EvidenceSource",
    "EvidenceTrace",
    "EventRecord",
    "EventType",
    "LlmOutputError",
    "NotFoundError",
    "PhrTarget",
    "PhrRecord",
    "PhrVerdict",
    "RankedDocument",
    "ReasoningTrace",
    "RepositoryError",
    "ValidationError",
    "validate_result_json",
    "VerificationTarget",
    "VerificationReport",
    "Verdict",
]
