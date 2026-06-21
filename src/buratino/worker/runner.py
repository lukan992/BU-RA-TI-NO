"""Job worker loop for buratino analysis."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from loguru import logger
from psycopg import connect
from psycopg.rows import dict_row

from buratino.models.job import BuratinoAnalysisJob
from buratino.repository.analysis_results import BuratinoEventAnalysisResultRepository
from buratino.repository.jobs import BuratinoAnalysisJobRepository, retry_at_after
from buratino.service.analysis import BuratinoAnalysisService
from buratino.service.errors import classify_error


@dataclass
class BuratinoWorker:
    analysis_service: BuratinoAnalysisService
    job_repository: BuratinoAnalysisJobRepository
    result_repository: BuratinoEventAnalysisResultRepository
    worker_id: str
    poll_interval_seconds: int
    lease_seconds: int
    heartbeat_seconds: int
    dsn: str

    def run(self, *, once: bool = False, max_jobs: int | None = None) -> int:
        processed = 0
        while True:
            job = self.job_repository.claim_next(worker_id=self.worker_id, lease_seconds=self.lease_seconds)
            if job is None:
                if once or max_jobs is not None:
                    logger.info("No eligible jobs found; worker exits after processing {} jobs.", processed)
                    return processed
                time.sleep(self.poll_interval_seconds)
                continue
            logger.info(
                "claimed job job_id={} event_id={} result_value_id={} attempts={} correlation_id={} payload={}",
                job.id,
                job.event_id,
                job.result_value_id,
                job.attempts,
                job.correlation_id,
                job.payload,
            )
            self._process_job(job)
            processed += 1
            if once or (max_jobs is not None and processed >= max_jobs):
                return processed

    def _process_job(self, job: BuratinoAnalysisJob) -> None:
        stop_event = threading.Event()
        heartbeat = threading.Thread(target=self._heartbeat_loop, args=(job.id, stop_event), daemon=True)
        heartbeat.start()
        try:
            payload = dict(job.payload or {})
            # The job columns are the source of truth for these identifiers; mirror
            # them into the payload so the result never loses result_value_id/report_id.
            if job.result_value_id is not None:
                payload["result_value_id"] = job.result_value_id
            if job.report_id is not None:
                payload["report_id"] = job.report_id
            result_json = self.analysis_service.analyze_event(job.event_id, job_id=str(job.id), payload=payload)
            with connect(self.dsn, row_factory=dict_row) as conn:
                with conn.transaction():
                    if not self.job_repository.renew_lease(
                        job_id=job.id,
                        worker_id=self.worker_id,
                        lease_seconds=self.lease_seconds,
                        connection=conn,
                    ):
                        raise RuntimeError("Job lease was lost before completion.")
                    logger.info("saving result job_id={}", job.id)
                    result_id = self.result_repository.save_result(job=job, result_json=result_json, connection=conn)
                    logger.info("saved buratino_event_analysis_results result_id={}", result_id)
                    ok = self.job_repository.complete(
                        job_id=job.id,
                        worker_id=self.worker_id,
                        result_payload={
                            "ok": True,
                            "result_id": str(result_id),
                            "event_id": result_json["event_id"],
                            "event_description_status": result_json["statuses"]["event_description_status"],
                            "phr_status": result_json["statuses"]["phr_status"],
                            "plan_status": result_json["statuses"]["plan_status"],
                            "supporting_files_count": len(result_json["supporting_files"]),
                        },
                        connection=conn,
                    )
                    if not ok:
                        raise RuntimeError("Failed to complete claimed job.")
            logger.info("completed job job_id={} result_id={}", job.id, result_id)
        except Exception as exc:
            classified = classify_error(exc)
            fail_applied = self.job_repository.fail(
                job_id=job.id,
                worker_id=self.worker_id,
                retryable=classified.retryable,
                last_error=str(exc),
                error_type=classified.error_type,
                error_stage=classified.error_stage,
                retry_at=retry_at_after(self.poll_interval_seconds),
            )
            logger.error(
                "failed job job_id={} error_type={} error_stage={} last_error={} retryable={} attempts={}/{} next_status={} fail_update_applied={}",
                job.id,
                classified.error_type,
                classified.error_stage,
                exc,
                classified.retryable,
                job.attempts,
                job.max_attempts,
                "pending" if classified.retryable and job.attempts < job.max_attempts else "failed",
                fail_applied,
            )
        finally:
            stop_event.set()
            heartbeat.join(timeout=1.0)

    def _heartbeat_loop(self, job_id, stop_event: threading.Event) -> None:
        while not stop_event.wait(self.heartbeat_seconds):
            ok = self.job_repository.renew_lease(
                job_id=job_id,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
            )
            if not ok:
                logger.warning("Lease renewal failed for job {}", job_id)
                return
