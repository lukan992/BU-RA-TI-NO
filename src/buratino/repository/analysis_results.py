"""Persistence for independent buratino analysis results."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from psycopg import connect
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from buratino.models.errors import RepositoryError
from buratino.models.job import BuratinoAnalysisJob
from buratino.models.result_contract import validate_result_json


@dataclass
class BuratinoEventAnalysisResultRepository:
    dsn: str

    def save_result(
        self,
        *,
        job: BuratinoAnalysisJob,
        result_json: dict,
        connection=None,
    ) -> UUID:
        validate_result_json(result_json)
        query = """
            INSERT INTO buratino_event_analysis_results (
                job_id,
                event_id,
                report_id,
                result_value_id,
                pipeline_name,
                pipeline_version,
                event_name,
                event_description_status,
                event_description_expected,
                event_description_fact,
                phr_status,
                phr_expected,
                phr_fact,
                plan_status,
                plan_expected,
                plan_fact,
                supporting_files,
                supporting_document_ids,
                evidence_items,
                diagnostic_reason,
                result_json
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING id
        """
        params = (
            str(job.id),
            result_json["event_id"],
            result_json["report_id"],
            result_json["result_value_id"],
            result_json["pipeline_name"],
            result_json["pipeline_version"],
            result_json["event_name"],
            result_json["statuses"]["event_description_status"],
            result_json["expected"]["event_description"],
            result_json["facts"]["event_description_fact"],
            result_json["statuses"]["phr_status"],
            result_json["expected"]["phr"],
            result_json["facts"]["phr_fact"],
            result_json["statuses"]["plan_status"],
            result_json["expected"]["plan"],
            result_json["facts"]["plan_fact"],
            ", ".join(item["filename"] for item in result_json["supporting_files"]),
            Jsonb([item["document_id"] for item in result_json["supporting_files"] if item["document_id"] is not None]),
            Jsonb(result_json["evidence_items"]),
            result_json["diagnostics"]["diagnostic_reason"],
            Jsonb(result_json),
        )
        if connection is not None:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                row = cursor.fetchone()
                return row["id"]
        with self._connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                row = cursor.fetchone()
                return row["id"]

    def _connection(self):
        try:
            return connect(self.dsn, row_factory=dict_row)
        except Exception as exc:  # pragma: no cover
            raise RepositoryError(f"Failed to connect to PostgreSQL: {exc}") from exc

    def get_result_by_id(self, result_id: str | UUID) -> dict | None:
        query = """
            SELECT
                id AS result_id,
                event_id,
                result_value_id,
                event_description_status,
                plan_status,
                phr_status,
                supporting_files,
                diagnostic_reason,
                created_at
            FROM buratino_event_analysis_results
            WHERE id = %s
            LIMIT 1
        """
        with self._connection() as conn, conn.cursor() as cursor:
            cursor.execute(query, (str(result_id),))
            return cursor.fetchone()

    def get_latest_result(self, *, event_id: int, result_value_id: int | None) -> dict | None:
        query = """
            SELECT
                id AS result_id,
                event_id,
                result_value_id,
                event_description_status,
                plan_status,
                phr_status,
                supporting_files,
                diagnostic_reason,
                created_at
            FROM buratino_event_analysis_results
            WHERE event_id = %s
              AND (%s IS NULL OR result_value_id = %s)
            ORDER BY created_at DESC
            LIMIT 1
        """
        with self._connection() as conn, conn.cursor() as cursor:
            cursor.execute(query, (event_id, result_value_id, result_value_id))
            return cursor.fetchone()
