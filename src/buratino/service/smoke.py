"""Local smoke seed and verification helpers for the worker pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from psycopg import connect
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from buratino.models.errors import ValidationError
from buratino.service.migrations import MigrationRunner

SMOKE_EVENT_IDS = (1001, 1002, 1003, 1004)
FAIL_EVENT_ID = 1999


@dataclass(frozen=True)
class SmokeSeedResult:
    seeded_event_ids: list[int]
    seeded_job_ids: int
    include_fail_case: bool


@dataclass(frozen=True)
class SmokeCheckResult:
    completed_events: list[int]
    checked_results: int
    include_fail_case: bool


def seed_smoke_db(*, dsn: str, include_fail_case: bool = False) -> SmokeSeedResult:
    MigrationRunner(dsn=dsn, migrations_dir=_migrations_dir()).run()
    smoke_ids = list(SMOKE_EVENT_IDS) + ([FAIL_EVENT_ID] if include_fail_case else [])
    with connect(dsn, row_factory=dict_row) as conn:
        with conn.transaction():
            _ensure_source_tables(conn)
            _cleanup(conn, smoke_ids)
            for case in _smoke_cases(include_fail_case=include_fail_case):
                _insert_case(conn, case)
    return SmokeSeedResult(
        seeded_event_ids=smoke_ids,
        seeded_job_ids=len(smoke_ids),
        include_fail_case=include_fail_case,
    )


def run_smoke_check(*, dsn: str, include_fail_case: bool = False) -> SmokeCheckResult:
    expected_ids = list(SMOKE_EVENT_IDS)
    with connect(dsn, row_factory=dict_row) as conn:
        jobs = _load_jobs(conn, expected_ids + ([FAIL_EVENT_ID] if include_fail_case else []))
        results = _load_results(conn, expected_ids)

    for event_id in expected_ids:
        job = jobs.get(event_id)
        if job is None:
            raise ValidationError(f"Smoke check failed: job for event_id={event_id} was not found.")
        if job["status"] != "completed":
            raise ValidationError(
                f"Smoke check failed: job for event_id={event_id} has status={job['status']!r}, expected 'completed'."
            )
    if len(results) != len(expected_ids):
        raise ValidationError(
            f"Smoke check failed: expected {len(expected_ids)} result rows, got {len(results)}."
        )

    _assert_result(
        results[1001],
        event_status="Подтверждено",
        plan_status="Подтверждено",
        diagnostic_substring="OCR-подтверждение",
    )
    _assert_result(
        results[1002],
        event_status="Не подтверждено",
        plan_status="Не подтверждено",
        diagnostic_substring="планового значения",
    )
    _assert_result(
        results[1003],
        event_status="Не подтверждено",
        plan_status="Не подтверждено",
        diagnostic_substring="8",
        extra_substring="12",
    )
    _assert_result(
        results[1004],
        event_status="Не подтверждено",
        plan_status="Не подтверждено",
        diagnostic_substring="OCR отсутствует",
    )

    for event_id, row in results.items():
        result_json = row["result_json"]
        diagnostics = result_json["diagnostics"]
        if diagnostics["evidence_source_used"] != "ocr":
            raise ValidationError(
                f"Smoke check failed: event_id={event_id} evidence_source_used={diagnostics['evidence_source_used']!r}."
            )
        evidence_items = result_json["evidence_items"]
        if any("summary" in str(item).lower() for item in evidence_items):
            raise ValidationError(f"Smoke check failed: event_id={event_id} used summary evidence.")

    if include_fail_case:
        failed_job = jobs.get(FAIL_EVENT_ID)
        if failed_job is None:
            raise ValidationError("Smoke check failed: fail-case job was not found.")
        if failed_job["status"] != "failed":
            raise ValidationError(
                f"Smoke check failed: fail-case job status={failed_job['status']!r}, expected 'failed'."
            )
        if failed_job["result_payload"] is not None:
            raise ValidationError("Smoke check failed: fail-case job unexpectedly has result_payload.")

    return SmokeCheckResult(
        completed_events=expected_ids,
        checked_results=len(results),
        include_fail_case=include_fail_case,
    )


def _assert_result(
    row: dict,
    *,
    event_status: str,
    plan_status: str,
    diagnostic_substring: str,
    extra_substring: str | None = None,
) -> None:
    if row["event_description_status"] != event_status:
        raise ValidationError(
            f"Smoke check failed: event_id={row['event_id']} event_description_status={row['event_description_status']!r}."
        )
    if row["plan_status"] != plan_status:
        raise ValidationError(f"Smoke check failed: event_id={row['event_id']} plan_status={row['plan_status']!r}.")
    diagnostic = row["diagnostic_reason"] or ""
    if diagnostic_substring not in diagnostic:
        raise ValidationError(
            f"Smoke check failed: event_id={row['event_id']} diagnostic_reason={diagnostic!r} does not contain {diagnostic_substring!r}."
        )
    if extra_substring is not None and extra_substring not in diagnostic:
        raise ValidationError(
            f"Smoke check failed: event_id={row['event_id']} diagnostic_reason={diagnostic!r} does not contain {extra_substring!r}."
        )


def _ensure_source_tables(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS xlsx_events (
            event_id BIGINT PRIMARY KEY,
            result_value_id BIGINT NULL,
            event_name TEXT NOT NULL,
            event_description TEXT NULL,
            planned_value NUMERIC NULL,
            planned_unit TEXT NULL,
            implementation_deadline TEXT NULL
        );
        CREATE TABLE IF NOT EXISTS xlsx_event_phr (
            event_id BIGINT PRIMARY KEY,
            result_value_id BIGINT NULL,
            phr_name TEXT NOT NULL,
            phr_value_2025 NUMERIC NULL,
            phr_unit TEXT NULL
        );
        CREATE TABLE IF NOT EXISTS documents (
            document_id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            file_name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS document_summary_results (
            document_id TEXT PRIMARY KEY,
            summary_text TEXT NULL
        );
        CREATE TABLE IF NOT EXISTS ocr_results (
            id BIGSERIAL PRIMARY KEY,
            document_id TEXT NOT NULL,
            page INTEGER NULL,
            full_text TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


def _cleanup(conn, smoke_ids: list[int]) -> None:
    doc_ids = [f"smoke-doc-{event_id}" for event_id in smoke_ids]
    conn.execute("DELETE FROM buratino_event_analysis_results WHERE event_id = ANY(%s)", (smoke_ids,))
    conn.execute("DELETE FROM buratino_analysis_jobs WHERE event_id = ANY(%s)", (smoke_ids,))
    conn.execute("DELETE FROM ocr_results WHERE document_id = ANY(%s)", (doc_ids,))
    conn.execute("DELETE FROM document_summary_results WHERE document_id = ANY(%s)", (doc_ids,))
    conn.execute("DELETE FROM documents WHERE document_id = ANY(%s)", (doc_ids,))
    conn.execute("DELETE FROM xlsx_event_phr WHERE event_id = ANY(%s)", (smoke_ids,))
    conn.execute("DELETE FROM xlsx_events WHERE event_id = ANY(%s)", (smoke_ids,))


def _load_jobs(conn, event_ids: list[int]) -> dict[int, dict]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT event_id, status, result_payload
            FROM buratino_analysis_jobs
            WHERE event_id = ANY(%s)
            """,
            (event_ids,),
        )
        rows = cursor.fetchall()
    return {int(row["event_id"]): row for row in rows}


def _load_results(conn, event_ids: list[int]) -> dict[int, dict]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT event_id, event_description_status, plan_status, diagnostic_reason, result_json
            FROM buratino_event_analysis_results
            WHERE event_id = ANY(%s)
            """,
            (event_ids,),
        )
        rows = cursor.fetchall()
    return {int(row["event_id"]): row for row in rows}


@dataclass(frozen=True)
class _SmokeCase:
    event_id: int
    result_value_id: int
    event_name: str
    event_description: str
    planned_value: int
    phr_name: str
    phr_value: int
    ocr_text: str | None
    summary_text: str


def _smoke_cases(*, include_fail_case: bool) -> list[_SmokeCase]:
    cases = [
        _SmokeCase(
            event_id=1001,
            result_value_id=2001,
            event_name="Поставка оборудования",
            event_description="Поставка оборудования для учреждения",
            planned_value=12,
            phr_name="Количество поставленного оборудования",
            phr_value=12,
            ocr_text="SMOKE_PASS_OVERFULFILLED Поставка оборудования выполнена в объеме 15 ед. при плане 12 ед.",
            summary_text="summary says success but must not be used",
        ),
        _SmokeCase(
            event_id=1002,
            result_value_id=2002,
            event_name="Поставка оборудования",
            event_description="Поставка оборудования для учреждения",
            planned_value=12,
            phr_name="Количество поставленного оборудования",
            phr_value=12,
            ocr_text="SMOKE_SEMANTIC_ONLY Поставка выполнена, оборудование поставлено.",
            summary_text="summary says 20 units delivered but must not be used",
        ),
        _SmokeCase(
            event_id=1003,
            result_value_id=2003,
            event_name="Поставка оборудования",
            event_description="Поставка оборудования для учреждения",
            planned_value=12,
            phr_name="Количество поставленного оборудования",
            phr_value=12,
            ocr_text="SMOKE_BELOW_PLAN Поставка выполнена в объеме 8 ед. при плане 12 ед.",
            summary_text="summary says plan met but must not be used",
        ),
        _SmokeCase(
            event_id=1004,
            result_value_id=2004,
            event_name="Поставка оборудования",
            event_description="Поставка оборудования для учреждения",
            planned_value=12,
            phr_name="Количество поставленного оборудования",
            phr_value=12,
            ocr_text=None,
            summary_text="summary says 30 units delivered but OCR is absent",
        ),
    ]
    if include_fail_case:
        cases.append(
            _SmokeCase(
                event_id=FAIL_EVENT_ID,
                result_value_id=2999,
                event_name="Missing event",
                event_description="Should fail with missing event",
                planned_value=12,
                phr_name="Missing PHR",
                phr_value=12,
                ocr_text="SMOKE_PASS_OVERFULFILLED",
                summary_text="not used",
            )
        )
    return cases


def _insert_case(conn, case: _SmokeCase) -> None:
    if case.event_id != FAIL_EVENT_ID:
        conn.execute(
            """
            INSERT INTO xlsx_events (
                event_id,
                result_value_id,
                event_name,
                event_description,
                planned_value,
                planned_unit,
                implementation_deadline
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                case.event_id,
                case.result_value_id,
                case.event_name,
                case.event_description,
                case.planned_value,
                "ед",
                None,
            ),
        )
        conn.execute(
            """
            INSERT INTO xlsx_event_phr (
                event_id,
                result_value_id,
                phr_name,
                phr_value_2025,
                phr_unit
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (
                case.event_id,
                case.result_value_id,
                case.phr_name,
                case.phr_value,
                "ед",
            ),
        )
    document_id = f"smoke-doc-{case.event_id}"
    conn.execute(
        "INSERT INTO documents (document_id, event_id, file_name) VALUES (%s, %s, %s)",
        (document_id, str(case.event_id), f"smoke-{case.event_id}.pdf"),
    )
    conn.execute(
        "INSERT INTO document_summary_results (document_id, summary_text) VALUES (%s, %s)",
        (document_id, case.summary_text),
    )
    if case.ocr_text is not None:
        conn.execute(
            "INSERT INTO ocr_results (document_id, page, full_text) VALUES (%s, %s, %s)",
            (document_id, 1, case.ocr_text),
        )
    conn.execute(
        """
        INSERT INTO buratino_analysis_jobs (
            event_id,
            report_id,
            result_value_id,
            status,
            priority,
            payload,
            max_attempts
        ) VALUES (%s, %s, %s, 'pending', %s, %s, %s)
        """,
        (
            case.event_id,
            case.result_value_id,
            case.result_value_id,
            100,
            Jsonb({"report_id": case.result_value_id, "result_value_id": case.result_value_id}),
            1 if case.event_id == FAIL_EVENT_ID else 3,
        ),
    )


def _migrations_dir():
    from pathlib import Path

    return Path("migrations")
