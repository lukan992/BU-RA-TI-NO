"""Job repository for buratino worker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from psycopg import connect
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from buratino.models.job import BuratinoAnalysisJob
from buratino.models.errors import RepositoryError


@dataclass
class BuratinoAnalysisJobRepository:
    dsn: str

    def claim_next(self, *, worker_id: str, lease_seconds: int) -> BuratinoAnalysisJob | None:
        query = """
            SELECT id
            FROM buratino_analysis_jobs
            WHERE (
                status = 'pending'
                AND available_at <= now()
            ) OR (
                status = 'claimed'
                AND lease_expires_at <= now()
            )
            ORDER BY priority DESC, available_at ASC, created_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        """
        update_query = """
            UPDATE buratino_analysis_jobs
            SET
                status = 'claimed',
                attempts = attempts + 1,
                claimed_by = %s,
                claimed_at = now(),
                lease_expires_at = now() + (%s * interval '1 second'),
                updated_at = now()
            WHERE id = %s
            RETURNING *
        """
        with self._connection() as conn:
            with conn.transaction():
                with conn.cursor() as cursor:
                    cursor.execute(query)
                    row = cursor.fetchone()
                    if row is None:
                        return None
                    cursor.execute(update_query, (worker_id, lease_seconds, row["id"]))
                    claimed = cursor.fetchone()
            return _row_to_job(claimed) if claimed is not None else None

    def find_active_job(self, *, event_id: int, result_value_id: int | None) -> dict | None:
        query = """
            SELECT id, status, event_id, result_value_id
            FROM buratino_analysis_jobs
            WHERE event_id = %s
              AND (
                    (%s IS NULL AND result_value_id IS NULL)
                 OR result_value_id = %s
              )
              AND status IN ('pending', 'claimed')
            ORDER BY created_at DESC
            LIMIT 1
        """
        with self._connection() as conn, conn.cursor() as cursor:
            cursor.execute(query, (event_id, result_value_id, result_value_id))
            return cursor.fetchone()

    def enqueue_debug_job(
        self,
        *,
        event_id: int,
        result_value_id: int | None,
        priority: int,
        max_attempts: int,
        correlation_id: str,
        payload: dict,
    ) -> UUID:
        query = """
            INSERT INTO buratino_analysis_jobs (
                event_id,
                report_id,
                result_value_id,
                status,
                priority,
                payload,
                max_attempts,
                available_at,
                correlation_id
            ) VALUES (%s, %s, %s, 'pending', %s, %s, %s, now(), %s)
            RETURNING id
        """
        with self._connection() as conn, conn.cursor() as cursor:
            cursor.execute(
                query,
                (
                    event_id,
                    result_value_id,
                    result_value_id,
                    priority,
                    Jsonb(payload),
                    max_attempts,
                    correlation_id,
                ),
            )
            row = cursor.fetchone()
            conn.commit()
            return row["id"]

    def get_latest_job(self, *, event_id: int, result_value_id: int | None) -> dict | None:
        query = """
            SELECT
                id,
                event_id,
                result_value_id,
                status,
                attempts,
                max_attempts,
                claimed_by,
                last_error,
                error_type,
                error_stage,
                result_payload,
                correlation_id,
                completed_at,
                created_at
            FROM buratino_analysis_jobs
            WHERE event_id = %s
              AND (%s IS NULL OR result_value_id = %s)
            ORDER BY created_at DESC
            LIMIT 1
        """
        with self._connection() as conn, conn.cursor() as cursor:
            cursor.execute(query, (event_id, result_value_id, result_value_id))
            return cursor.fetchone()

    def renew_lease(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        lease_seconds: int,
        connection=None,
    ) -> bool:
        query = """
            UPDATE buratino_analysis_jobs
            SET lease_expires_at = now() + (%s * interval '1 second'),
                updated_at = now()
            WHERE id = %s
              AND status = 'claimed'
              AND claimed_by = %s
              AND lease_expires_at > now()
        """
        return self._execute_rowcount(
            query,
            (lease_seconds, str(job_id), worker_id),
            connection=connection,
        )

    def complete(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        result_payload: dict,
        connection=None,
    ) -> bool:
        query = """
            UPDATE buratino_analysis_jobs
            SET status = 'completed',
                result_payload = %s,
                completed_at = now(),
                updated_at = now()
            WHERE id = %s
              AND status = 'claimed'
              AND claimed_by = %s
        """
        return self._execute_rowcount(
            query,
            (Jsonb(result_payload), str(job_id), worker_id),
            connection=connection,
        )

    def fail(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        retryable: bool,
        last_error: str,
        error_type: str,
        error_stage: str,
        retry_at: datetime | None = None,
        connection=None,
    ) -> bool:
        if retryable:
            query = """
                UPDATE buratino_analysis_jobs
                SET status = CASE WHEN attempts < max_attempts THEN 'pending' ELSE 'failed' END,
                    claimed_by = CASE WHEN attempts < max_attempts THEN NULL ELSE claimed_by END,
                    claimed_at = CASE WHEN attempts < max_attempts THEN NULL ELSE claimed_at END,
                    lease_expires_at = CASE WHEN attempts < max_attempts THEN NULL ELSE lease_expires_at END,
                    completed_at = CASE WHEN attempts < max_attempts THEN NULL ELSE now() END,
                    last_error = %s,
                    error_type = %s,
                    error_stage = %s,
                    available_at = CASE WHEN attempts < max_attempts THEN %s ELSE available_at END,
                    updated_at = now()
                WHERE id = %s
                  AND status = 'claimed'
                  AND claimed_by = %s
            """
            params = (last_error, error_type, error_stage, retry_at or datetime.now(timezone.utc), str(job_id), worker_id)
        else:
            query = """
                UPDATE buratino_analysis_jobs
                SET status = 'failed',
                    last_error = %s,
                    error_type = %s,
                    error_stage = %s,
                    completed_at = now(),
                    updated_at = now()
                WHERE id = %s
                  AND status = 'claimed'
                  AND claimed_by = %s
            """
            params = (last_error, error_type, error_stage, str(job_id), worker_id)
        return self._execute_rowcount(query, params, connection=connection)

    def _execute_rowcount(self, query: str, params: tuple, *, connection=None) -> bool:
        if connection is not None:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                return cursor.rowcount > 0
        with self._connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                return cursor.rowcount > 0

    def _connection(self):
        try:
            return connect(self.dsn, row_factory=dict_row)
        except Exception as exc:  # pragma: no cover
            raise RepositoryError(f"Failed to connect to PostgreSQL: {exc}") from exc


def retry_at_after(seconds: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def _row_to_job(row: dict) -> BuratinoAnalysisJob:
    return BuratinoAnalysisJob(**row)
