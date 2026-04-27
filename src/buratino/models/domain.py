"""Core domain models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Verdict = Literal["подтверждено", "не подтверждено"]
PhrVerdict = Literal["подтверждено", "не подтверждено", "не указано"]
EventType = Literal["qualitative", "quantitative"]
ComparisonResult = Literal["meets_target", "below_target", "not_applicable", "insufficient_data"]
EvidenceSource = Literal["summary", "ocr"]


@dataclass(frozen=True)
class EventRecord:
    event_id: int
    event_name: str
    event_description: str | None
    planned_value: float | None
    planned_unit: str | None
    source_table: str | None = None


@dataclass(frozen=True)
class PhrRecord:
    event_id: int
    phr_name: str
    phr_value_2025: float | None
    phr_unit: str | None
    source_table: str | None = None


@dataclass(frozen=True)
class DocumentSummary:
    document_id: str | None
    file_name: str
    evidence_text: str
    evidence_source: EvidenceSource
    source_table: str | None = None


@dataclass(frozen=True)
class VerificationTarget:
    event_id: int
    event_name: str
    event_description: str | None
    event_type: EventType | None
    normalized_action: str | None
    normalized_subject: str | None
    planned_value: float | None
    planned_unit: str | None


@dataclass(frozen=True)
class PhrTarget:
    event_id: int
    event_name: str
    phr_name: str
    phr_value_2025: float | None
    phr_unit: str | None
