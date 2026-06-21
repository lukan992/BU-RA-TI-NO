from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest

from buratino.config.errors import ConfigurationError
from buratino.service.integration_debug import (
    enqueue_debug_job,
    inspect_job,
    require_debug_commands_allowed,
    sanitize_dsn,
)


def test_sanitize_dsn_hides_password() -> None:
    sanitized = sanitize_dsn("postgresql://user:secret@db.example.com:5432/test_db")

    assert sanitized == "postgresql://user@db.example.com:5432/test_db"
    assert "secret" not in sanitized


def test_require_debug_commands_allowed_rejects_without_flag() -> None:
    with pytest.raises(ConfigurationError, match="Refusing to create debug job"):
        require_debug_commands_allowed(env_allowed=False, cli_allowed=False)


def test_enqueue_debug_job_creates_pending_job() -> None:
    repository = FakeJobRepository(active_job=None)

    result = enqueue_debug_job(
        repository=repository,
        event_id=1001,
        result_value_id=2001,
        priority=100,
        max_attempts=1,
        correlation_id=None,
        payload_json='{"note":"test"}',
    )

    assert result.created is True
    assert result.status == "pending"
    assert repository.inserted_payload == {"mode": "ocr_only", "source": "manual-debug", "note": "test"}


def test_enqueue_debug_job_does_not_create_duplicate_active_job() -> None:
    repository = FakeJobRepository(active_job={"id": uuid4(), "status": "pending"})

    result = enqueue_debug_job(
        repository=repository,
        event_id=1001,
        result_value_id=2001,
        priority=100,
        max_attempts=1,
        correlation_id=None,
        payload_json=None,
    )

    assert result.created is False
    assert result.status == "pending"


@dataclass
class FakeInspectJobRepository:
    job: dict | None

    def get_latest_job(self, *, event_id: int, result_value_id: int | None):
        del event_id, result_value_id
        return self.job


@dataclass
class FakeInspectResultRepository:
    by_id: dict | None = None
    latest: dict | None = None
    requested_id: str | None = None

    def get_result_by_id(self, result_id):
        self.requested_id = result_id
        return self.by_id

    def get_latest_result(self, *, event_id: int, result_value_id: int | None):
        del event_id, result_value_id
        return self.latest


def test_inspect_job_uses_result_id_from_result_payload() -> None:
    job = {"id": uuid4(), "status": "completed", "result_payload": {"result_id": "res-123"}}
    job_repository = FakeInspectJobRepository(job=job)
    result_repository = FakeInspectResultRepository(
        by_id={"result_id": "res-123", "result_value_id": 2001},
        latest={"result_id": "stale", "result_value_id": None},
    )

    inspected = inspect_job(
        job_repository=job_repository,
        result_repository=result_repository,
        event_id=1001,
        result_value_id=2001,
    )

    assert result_repository.requested_id == "res-123"
    assert inspected.result == {"result_id": "res-123", "result_value_id": 2001}


def test_inspect_job_falls_back_to_latest_when_no_result_payload() -> None:
    job = {"id": uuid4(), "status": "pending", "result_payload": None}
    job_repository = FakeInspectJobRepository(job=job)
    result_repository = FakeInspectResultRepository(
        by_id=None,
        latest={"result_id": "latest-1", "result_value_id": 2001},
    )

    inspected = inspect_job(
        job_repository=job_repository,
        result_repository=result_repository,
        event_id=1001,
        result_value_id=2001,
    )

    assert result_repository.requested_id is None
    assert inspected.result == {"result_id": "latest-1", "result_value_id": 2001}


@dataclass
class FakeJobRepository:
    active_job: dict | None
    inserted_payload: dict | None = None

    def find_active_job(self, *, event_id: int, result_value_id: int | None):
        del event_id, result_value_id
        return self.active_job

    def enqueue_debug_job(
        self,
        *,
        event_id: int,
        result_value_id: int | None,
        priority: int,
        max_attempts: int,
        correlation_id: str,
        payload: dict,
    ):
        del event_id, result_value_id, priority, max_attempts, correlation_id
        self.inserted_payload = payload
        return uuid4()
