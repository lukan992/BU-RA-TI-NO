"""Worker job models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class BuratinoAnalysisJob:
    id: UUID
    event_id: int
    report_id: int | None
    result_value_id: int | None
    status: str
    priority: int
    payload: dict
    result_payload: dict | None
    attempts: int
    max_attempts: int
    available_at: datetime
    claimed_by: str | None
    claimed_at: datetime | None
    lease_expires_at: datetime | None
    last_error: str | None
    error_type: str | None
    error_stage: str | None
    correlation_id: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
