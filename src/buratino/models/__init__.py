"""Domain and output contracts for buratino."""

from buratino.models.contracts import (
    AggregatedVerdict,
    AuditResult,
    DocumentFactResult,
    DocumentPhrResult,
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
    "BuratinoError",
    "ComparisonResult",
    "DataContractError",
    "DocumentFactResult",
    "DocumentPhrResult",
    "DocumentSummary",
    "EvidenceSource",
    "EventRecord",
    "EventType",
    "LlmOutputError",
    "NotFoundError",
    "PhrTarget",
    "PhrRecord",
    "PhrVerdict",
    "RepositoryError",
    "ValidationError",
    "VerificationTarget",
    "VerificationReport",
    "Verdict",
]
