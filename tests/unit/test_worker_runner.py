from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from uuid import uuid4

from buratino.models.job import BuratinoAnalysisJob
from buratino.worker.runner import BuratinoWorker


def _job() -> BuratinoAnalysisJob:
    now = datetime.now(timezone.utc)
    return BuratinoAnalysisJob(
        id=uuid4(),
        event_id=42,
        report_id=None,
        result_value_id=None,
        status="claimed",
        priority=0,
        payload={},
        result_payload=None,
        attempts=1,
        max_attempts=3,
        available_at=now,
        claimed_by="worker-1",
        claimed_at=now,
        lease_expires_at=now,
        last_error=None,
        error_type=None,
        error_stage=None,
        correlation_id=None,
        created_at=now,
        updated_at=now,
        completed_at=None,
    )


@dataclass
class FakeAnalysisService:
    payload: dict | None = None
    exc: Exception | None = None

    def analyze_event(self, event_id: int, *, job_id=None, payload=None):
        if self.exc is not None:
            raise self.exc
        return self.payload


@dataclass
class FakeJobRepository:
    completed: list[dict] | None = None
    failed: list[dict] | None = None
    jobs: list[BuratinoAnalysisJob] | None = None

    def __post_init__(self) -> None:
        self.completed = []
        self.failed = []
        self.jobs = []

    def claim_next(self, *, worker_id: str, lease_seconds: int):
        del worker_id, lease_seconds
        if not self.jobs:
            return None
        return self.jobs.pop(0)

    def renew_lease(self, *, job_id, worker_id: str, lease_seconds: int, connection=None):
        return True

    def complete(self, *, job_id, worker_id: str, result_payload: dict, connection=None):
        self.completed.append(result_payload)
        return True

    def fail(self, *, job_id, worker_id: str, retryable: bool, last_error: str, error_type: str, error_stage: str, retry_at=None, connection=None):
        self.failed.append(
            {
                "retryable": retryable,
                "last_error": last_error,
                "error_type": error_type,
                "error_stage": error_stage,
            }
        )
        return True


@dataclass
class FakeResultRepository:
    def save_result(self, *, job, result_json: dict, connection=None):
        return uuid4()


def test_worker_process_job_completes_successfully(monkeypatch) -> None:
    monkeypatch.setattr("buratino.worker.runner.connect", lambda *args, **kwargs: _FakeConnection())
    worker = BuratinoWorker(
        analysis_service=FakeAnalysisService(
            payload={
                "event_id": 42,
                "statuses": {
                    "event_description_status": "Подтверждено",
                    "phr_status": "Не применимо",
                    "plan_status": "Подтверждено",
                },
                "supporting_files": [{"filename": "report.pdf"}],
            }
        ),
        job_repository=FakeJobRepository(),
        result_repository=FakeResultRepository(),
        worker_id="worker-1",
        poll_interval_seconds=1,
        lease_seconds=10,
        heartbeat_seconds=1,
        dsn="postgresql://runtime",
    )

    worker._process_job(_job())

    assert len(worker.job_repository.completed) == 1
    assert worker.job_repository.failed == []


def test_worker_process_job_marks_retryable_failure(monkeypatch) -> None:
    monkeypatch.setattr("buratino.worker.runner.connect", lambda *args, **kwargs: _FakeConnection())
    worker = BuratinoWorker(
        analysis_service=FakeAnalysisService(exc=RuntimeError("boom")),
        job_repository=FakeJobRepository(),
        result_repository=FakeResultRepository(),
        worker_id="worker-1",
        poll_interval_seconds=1,
        lease_seconds=10,
        heartbeat_seconds=1,
        dsn="postgresql://runtime",
    )

    worker._process_job(_job())

    assert worker.job_repository.completed == []
    assert len(worker.job_repository.failed) == 1


def test_worker_run_stops_after_max_jobs(monkeypatch) -> None:
    monkeypatch.setattr("buratino.worker.runner.connect", lambda *args, **kwargs: _FakeConnection())
    repo = FakeJobRepository()
    repo.jobs = [_job(), _job(), _job()]
    worker = BuratinoWorker(
        analysis_service=FakeAnalysisService(
            payload={
                "event_id": 42,
                "statuses": {
                    "event_description_status": "Подтверждено",
                    "phr_status": "Не применимо",
                    "plan_status": "Подтверждено",
                },
                "supporting_files": [{"filename": "report.pdf"}],
            }
        ),
        job_repository=repo,
        result_repository=FakeResultRepository(),
        worker_id="worker-1",
        poll_interval_seconds=1,
        lease_seconds=10,
        heartbeat_seconds=1,
        dsn="postgresql://runtime",
    )

    processed = worker.run(max_jobs=2)

    assert processed == 2
    assert len(worker.job_repository.completed) == 2


@dataclass
class _CapturingAnalysisService:
    received_payload: dict | None = None

    def analyze_event(self, event_id: int, *, job_id=None, payload=None):
        del job_id
        self.received_payload = payload
        return {
            "event_id": event_id,
            "result_value_id": (payload or {}).get("result_value_id"),
            "statuses": {
                "event_description_status": "Подтверждено",
                "phr_status": "Не применимо",
                "plan_status": "Подтверждено",
            },
            "supporting_files": [{"filename": "report.pdf"}],
        }


@dataclass
class _CapturingResultRepository:
    saved_result_json: dict | None = None

    def save_result(self, *, job, result_json: dict, connection=None):
        del job, connection
        self.saved_result_json = result_json
        return uuid4()


def test_worker_completed_result_preserves_result_value_id(monkeypatch) -> None:
    monkeypatch.setattr("buratino.worker.runner.connect", lambda *args, **kwargs: _FakeConnection())
    job = replace(_job(), result_value_id=9187621740, payload={})
    analysis_service = _CapturingAnalysisService()
    result_repository = _CapturingResultRepository()
    worker = BuratinoWorker(
        analysis_service=analysis_service,
        job_repository=FakeJobRepository(),
        result_repository=result_repository,
        worker_id="worker-1",
        poll_interval_seconds=1,
        lease_seconds=10,
        heartbeat_seconds=1,
        dsn="postgresql://runtime",
    )

    worker._process_job(job)

    # The job column is mirrored into the analysis payload and into the saved result.
    assert analysis_service.received_payload["result_value_id"] == 9187621740
    assert result_repository.saved_result_json["result_value_id"] == 9187621740
    assert worker.job_repository.failed == []
    assert len(worker.job_repository.completed) == 1


def test_worker_run_once_exits_when_no_jobs() -> None:
    worker = BuratinoWorker(
        analysis_service=FakeAnalysisService(),
        job_repository=FakeJobRepository(),
        result_repository=FakeResultRepository(),
        worker_id="worker-1",
        poll_interval_seconds=1,
        lease_seconds=10,
        heartbeat_seconds=1,
        dsn="postgresql://runtime",
    )

    processed = worker.run(once=True)

    assert processed == 0


class _FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def execute(self, query, params):
        return None

    def fetchone(self):
        return {"id": uuid4()}


class _FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None


class _FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def transaction(self):
        return _FakeTransaction()

    def cursor(self):
        return _FakeCursor()
