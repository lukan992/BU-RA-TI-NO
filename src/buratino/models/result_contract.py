"""Independent buratino pipeline result contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from buratino.models.errors import ValidationError

BusinessStatus = Literal["Подтверждено", "Не подтверждено", "Не применимо", "Не проверялось"]
EvidenceSupport = Literal["event_description", "phr", "plan"]

BUSINESS_STATUSES: set[str] = {
    "Подтверждено",
    "Не подтверждено",
    "Не применимо",
    "Не проверялось",
}
EVIDENCE_SUPPORT_FIELDS: set[str] = {"event_description", "phr", "plan"}


@dataclass(frozen=True)
class ResultStatuses:
    event_description_status: BusinessStatus
    phr_status: BusinessStatus
    plan_status: BusinessStatus


@dataclass(frozen=True)
class ResultExpected:
    event_description: str | None
    phr: str | None
    plan: str | None


@dataclass(frozen=True)
class ResultFacts:
    event_description_fact: str | None
    phr_fact: str | None
    plan_fact: str | None


@dataclass(frozen=True)
class SupportingFileEntry:
    document_id: str | None
    filename: str
    reason: str


@dataclass(frozen=True)
class EvidenceItemEntry:
    document_id: str | None
    filename: str
    page_number: int | None
    chunk_id: str | None
    text_fragment: str
    supports: list[EvidenceSupport]


@dataclass(frozen=True)
class ResultDiagnostics:
    evidence_source_used: str
    ocr_available: bool
    analyzed_files: list[str] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    diagnostic_reason: str | None = None


@dataclass(frozen=True)
class ResultModelInfo:
    primary_model: str
    ranking_model: str | None
    audit_model: str | None


@dataclass(frozen=True)
class BuratinoResult:
    pipeline_name: str
    pipeline_version: str
    event_id: int
    report_id: int | None
    result_value_id: int | None
    event_name: str
    statuses: ResultStatuses
    expected: ResultExpected
    facts: ResultFacts
    supporting_files: list[SupportingFileEntry]
    evidence_items: list[EvidenceItemEntry]
    diagnostics: ResultDiagnostics
    model_info: ResultModelInfo

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_result_json(payload: dict[str, Any]) -> None:
    required_keys = {
        "pipeline_name",
        "pipeline_version",
        "event_id",
        "report_id",
        "result_value_id",
        "event_name",
        "statuses",
        "expected",
        "facts",
        "supporting_files",
        "evidence_items",
        "diagnostics",
        "model_info",
    }
    actual_keys = set(payload.keys())
    if actual_keys != required_keys:
        raise ValidationError(
            f"result_json schema mismatch: expected={sorted(required_keys)} actual={sorted(actual_keys)}"
        )

    if not isinstance(payload["pipeline_name"], str) or not payload["pipeline_name"].strip():
        raise ValidationError("pipeline_name must be a non-empty string.")
    if not isinstance(payload["pipeline_version"], str) or not payload["pipeline_version"].strip():
        raise ValidationError("pipeline_version must be a non-empty string.")
    if not isinstance(payload["event_id"], int):
        raise ValidationError("event_id must be an integer.")
    if payload["report_id"] is not None and not isinstance(payload["report_id"], int):
        raise ValidationError("report_id must be null or integer.")
    if payload["result_value_id"] is not None and not isinstance(payload["result_value_id"], int):
        raise ValidationError("result_value_id must be null or integer.")
    if not isinstance(payload["event_name"], str) or not payload["event_name"].strip():
        raise ValidationError("event_name must be a non-empty string.")

    _validate_statuses(payload["statuses"])
    _validate_nullable_strings(payload["expected"], {"event_description", "phr", "plan"})
    _validate_nullable_strings(payload["facts"], {"event_description_fact", "phr_fact", "plan_fact"})
    _validate_supporting_files(payload["supporting_files"])
    _validate_evidence_items(payload["evidence_items"])
    _validate_diagnostics(payload["diagnostics"])
    _validate_model_info(payload["model_info"])


def _validate_statuses(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ValidationError("statuses must be a JSON object.")
    expected_keys = {"event_description_status", "phr_status", "plan_status"}
    if set(payload.keys()) != expected_keys:
        raise ValidationError("statuses keys are invalid.")
    for key, value in payload.items():
        if value not in BUSINESS_STATUSES:
            raise ValidationError(f"{key} must be one of {sorted(BUSINESS_STATUSES)}.")


def _validate_nullable_strings(payload: Any, expected_keys: set[str]) -> None:
    if not isinstance(payload, dict):
        raise ValidationError("expected/facts must be JSON objects.")
    if set(payload.keys()) != expected_keys:
        raise ValidationError(f"object keys are invalid: expected {sorted(expected_keys)}.")
    for key, value in payload.items():
        if value is not None and not isinstance(value, str):
            raise ValidationError(f"{key} must be null or string.")


def _validate_supporting_files(payload: Any) -> None:
    if not isinstance(payload, list):
        raise ValidationError("supporting_files must be a list.")
    for item in payload:
        if not isinstance(item, dict):
            raise ValidationError("Each supporting_files item must be an object.")
        if set(item.keys()) != {"document_id", "filename", "reason"}:
            raise ValidationError("supporting_files item schema mismatch.")
        if item["document_id"] is not None and not isinstance(item["document_id"], str):
            raise ValidationError("supporting_files.document_id must be null or string.")
        if not isinstance(item["filename"], str) or not item["filename"].strip():
            raise ValidationError("supporting_files.filename must be a non-empty string.")
        if not isinstance(item["reason"], str) or not item["reason"].strip():
            raise ValidationError("supporting_files.reason must be a non-empty string.")


def _validate_evidence_items(payload: Any) -> None:
    if not isinstance(payload, list):
        raise ValidationError("evidence_items must be a list.")
    for item in payload:
        if not isinstance(item, dict):
            raise ValidationError("Each evidence_items item must be an object.")
        expected_keys = {
            "document_id",
            "filename",
            "page_number",
            "chunk_id",
            "text_fragment",
            "supports",
        }
        if set(item.keys()) != expected_keys:
            raise ValidationError("evidence_items item schema mismatch.")
        if item["document_id"] is not None and not isinstance(item["document_id"], str):
            raise ValidationError("evidence_items.document_id must be null or string.")
        if not isinstance(item["filename"], str) or not item["filename"].strip():
            raise ValidationError("evidence_items.filename must be a non-empty string.")
        if item["page_number"] is not None and not isinstance(item["page_number"], int):
            raise ValidationError("evidence_items.page_number must be null or integer.")
        if item["chunk_id"] is not None and not isinstance(item["chunk_id"], str):
            raise ValidationError("evidence_items.chunk_id must be null or string.")
        if not isinstance(item["text_fragment"], str) or not item["text_fragment"].strip():
            raise ValidationError("evidence_items.text_fragment must be a non-empty string.")
        if not isinstance(item["supports"], list) or not item["supports"]:
            raise ValidationError("evidence_items.supports must be a non-empty list.")
        for support in item["supports"]:
            if support not in EVIDENCE_SUPPORT_FIELDS:
                raise ValidationError(f"Unsupported evidence support field: {support}")


def _validate_diagnostics(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ValidationError("diagnostics must be an object.")
    expected_keys = {
        "evidence_source_used",
        "ocr_available",
        "analyzed_files",
        "skipped_files",
        "diagnostic_reason",
    }
    if set(payload.keys()) != expected_keys:
        raise ValidationError("diagnostics schema mismatch.")
    if payload["evidence_source_used"] != "ocr":
        raise ValidationError("diagnostics.evidence_source_used must be 'ocr'.")
    if not isinstance(payload["ocr_available"], bool):
        raise ValidationError("diagnostics.ocr_available must be boolean.")
    for key in ("analyzed_files", "skipped_files"):
        value = payload[key]
        if not isinstance(value, list):
            raise ValidationError(f"diagnostics.{key} must be a list.")
        if any(not isinstance(item, str) for item in value):
            raise ValidationError(f"diagnostics.{key} must contain strings only.")
    if payload["diagnostic_reason"] is not None and not isinstance(payload["diagnostic_reason"], str):
        raise ValidationError("diagnostics.diagnostic_reason must be null or string.")


def _validate_model_info(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ValidationError("model_info must be an object.")
    expected_keys = {"primary_model", "ranking_model", "audit_model"}
    if set(payload.keys()) != expected_keys:
        raise ValidationError("model_info schema mismatch.")
    if not isinstance(payload["primary_model"], str) or not payload["primary_model"].strip():
        raise ValidationError("model_info.primary_model must be a non-empty string.")
    for key in ("ranking_model", "audit_model"):
        value = payload[key]
        if value is not None and not isinstance(value, str):
            raise ValidationError(f"model_info.{key} must be null or string.")
