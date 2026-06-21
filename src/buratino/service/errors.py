"""Worker-facing error classification."""

from __future__ import annotations

from dataclasses import dataclass

from buratino.llm.json_runner import JsonStepFailure
from buratino.models.errors import DataContractError, NotFoundError, RepositoryError, ValidationError


class RetryableError(Exception):
    """Wrap retryable worker failures."""


class NonRetryableError(Exception):
    """Wrap permanent worker failures."""


@dataclass(frozen=True)
class ClassifiedError:
    retryable: bool
    error_type: str
    error_stage: str


def classify_error(exc: Exception) -> ClassifiedError:
    if isinstance(exc, JsonStepFailure):
        return ClassifiedError(retryable=True, error_type=exc.info.error_type, error_stage=exc.info.stage)
    if isinstance(exc, NotFoundError):
        return ClassifiedError(retryable=False, error_type="not_found", error_stage="load_event")
    if isinstance(exc, (ValidationError, DataContractError)):
        return ClassifiedError(retryable=False, error_type="invalid_input", error_stage="analysis")
    if isinstance(exc, RepositoryError):
        rendered = str(exc).lower()
        if "llm request failed" in rendered or "failed to connect" in rendered:
            return ClassifiedError(retryable=True, error_type="temporary_backend_error", error_stage="analysis")
        return ClassifiedError(retryable=True, error_type="repository_error", error_stage="analysis")
    return ClassifiedError(retryable=False, error_type="unexpected_error", error_stage="analysis")
