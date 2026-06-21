"""Helpers for manual integration checks against an existing OCR database."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit, urlunsplit

from buratino.config.errors import ConfigurationError
from buratino.models.errors import NotFoundError, ValidationError
from buratino.repository._postgres import PostgresIntrospector
from buratino.repository.analysis_results import BuratinoEventAnalysisResultRepository
from buratino.repository.events import PostgresEventRepository
from buratino.repository.jobs import BuratinoAnalysisJobRepository
from buratino.repository.summaries import (
    DOCUMENTS_TABLE,
    OCR_RESULTS_TABLE,
    SUMMARY_RESULTS_TABLE,
    XLSX_EVENTS_TABLE,
    PostgresSummaryRepository,
)


@dataclass(frozen=True)
class IntegrationPreflightResult:
    event_id: int
    result_value_id: int | None
    event_name: str
    planned_value: float | None
    planned_unit: str | None
    phr_found: bool
    required_tables: dict[str, bool]
    linked_documents_count: int
    documents_with_ocr_count: int
    documents_without_ocr_count: int
    ocr_total_chars: int
    ocr_preview: str | None
    summary_verdict_enabled: bool
    date_check_enabled: bool
    audit_enabled: bool
    ranking_enabled: bool
    warning: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class EnqueueDebugJobResult:
    created: bool
    job_id: str
    status: str
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class InspectJobResult:
    job: dict | None
    result: dict | None

    def to_dict(self) -> dict:
        return asdict(self)


def sanitize_dsn(dsn: str) -> str:
    parts = urlsplit(dsn)
    netloc = parts.hostname or ""
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    if parts.username:
        netloc = f"{parts.username}@{netloc}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def integration_preflight(
    *,
    dsn: str,
    schema: str,
    event_id: int,
    result_value_id: int | None,
    summary_verdict_enabled: bool,
    date_check_enabled: bool,
    audit_enabled: bool,
    ranking_enabled: bool,
    debug: bool = False,
) -> IntegrationPreflightResult:
    introspector = PostgresIntrospector(dsn, schema)
    event_repo = PostgresEventRepository(dsn=dsn, schema=schema)
    summary_repo = PostgresSummaryRepository(
        dsn=dsn,
        schema=schema,
        evidence_source_mode="ocr_only",
    )

    required_tables = {
        "buratino_analysis_jobs": introspector.table_exists("buratino_analysis_jobs"),
        "buratino_event_analysis_results": introspector.table_exists("buratino_event_analysis_results"),
        XLSX_EVENTS_TABLE: introspector.table_exists(XLSX_EVENTS_TABLE),
        DOCUMENTS_TABLE: introspector.table_exists(DOCUMENTS_TABLE),
        OCR_RESULTS_TABLE: introspector.table_exists(OCR_RESULTS_TABLE),
        SUMMARY_RESULTS_TABLE: introspector.table_exists(SUMMARY_RESULTS_TABLE),
    }
    event = event_repo.get_event(result_value_id or event_id)
    try:
        event_repo.get_event_phr(result_value_id or event_id)
        phr_found = True
    except NotFoundError:
        phr_found = False

    file_evidence = summary_repo.list_file_evidence(result_value_id or event_id)
    documents = len(file_evidence)
    with_ocr = sum(1 for item in file_evidence if item.ocr_text or item.ocr_parts)
    without_ocr = documents - with_ocr
    total_chars = sum(len(item.ocr_text or "") for item in file_evidence)
    preview = None
    if debug:
        first_with_ocr = next((item for item in file_evidence if item.ocr_text), None)
        preview = _short_preview(first_with_ocr.ocr_text or "") if first_with_ocr is not None else None
    warning = None
    if with_ocr == 0:
        warning = "OCR отсутствует: worker завершит job как completed business-negative."

    return IntegrationPreflightResult(
        event_id=event.event_id,
        result_value_id=result_value_id,
        event_name=event.event_name,
        planned_value=event.planned_value,
        planned_unit=event.planned_unit,
        phr_found=phr_found,
        required_tables=required_tables,
        linked_documents_count=documents,
        documents_with_ocr_count=with_ocr,
        documents_without_ocr_count=without_ocr,
        ocr_total_chars=total_chars,
        ocr_preview=preview,
        summary_verdict_enabled=summary_verdict_enabled,
        date_check_enabled=date_check_enabled,
        audit_enabled=audit_enabled,
        ranking_enabled=ranking_enabled,
        warning=warning,
    )


def require_debug_commands_allowed(*, env_allowed: bool, cli_allowed: bool) -> None:
    if env_allowed or cli_allowed:
        return
    raise ConfigurationError(
        "Refusing to create debug job. Set ALLOW_INTEGRATION_DEBUG_COMMANDS=true for non-production manual testing."
    )


def enqueue_debug_job(
    *,
    repository: BuratinoAnalysisJobRepository,
    event_id: int,
    result_value_id: int | None,
    priority: int,
    max_attempts: int,
    correlation_id: str | None,
    payload_json: str | None,
) -> EnqueueDebugJobResult:
    payload = {"mode": "ocr_only", "source": "manual-debug"}
    if payload_json:
        parsed = json.loads(payload_json)
        if not isinstance(parsed, dict):
            raise ValidationError("--payload-json must be a JSON object.")
        payload.update(parsed)
    final_correlation_id = correlation_id or f"manual-debug-{event_id}-{result_value_id or 'null'}"
    duplicate = repository.find_active_job(event_id=event_id, result_value_id=result_value_id)
    if duplicate is not None:
        return EnqueueDebugJobResult(
            created=False,
            job_id=str(duplicate["id"]),
            status=str(duplicate["status"]),
            message="Active job already exists for this event/result_value_id.",
        )
    job_id = repository.enqueue_debug_job(
        event_id=event_id,
        result_value_id=result_value_id,
        priority=priority,
        max_attempts=max_attempts,
        correlation_id=final_correlation_id,
        payload=payload,
    )
    return EnqueueDebugJobResult(
        created=True,
        job_id=str(job_id),
        status="pending",
        message="DEBUG ONLY: production jobs must be created by external orchestrator.",
    )


def inspect_job(
    *,
    job_repository: BuratinoAnalysisJobRepository,
    result_repository: BuratinoEventAnalysisResultRepository,
    event_id: int,
    result_value_id: int | None,
) -> InspectJobResult:
    job = job_repository.get_latest_job(event_id=event_id, result_value_id=result_value_id)

    result = None
    result_payload = job.get("result_payload") if job else None
    result_id = result_payload.get("result_id") if isinstance(result_payload, dict) else None
    if result_id:
        result = result_repository.get_result_by_id(result_id)
    if result is None:
        result = result_repository.get_latest_result(event_id=event_id, result_value_id=result_value_id)

    return InspectJobResult(job=job, result=result)


def _short_preview(text: str) -> str | None:
    cleaned = " ".join(text.split())
    if not cleaned:
        return None
    return cleaned[:300]
