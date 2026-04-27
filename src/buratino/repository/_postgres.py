"""PostgreSQL helper utilities."""

from __future__ import annotations

from collections.abc import Iterable

from psycopg import connect
from psycopg.rows import dict_row

from buratino.models.errors import DataContractError, RepositoryError


def normalize_column_name(name: str) -> str:
    lowered = name.strip().lower()
    return "".join(char for char in lowered if char.isalnum())


def quote_ident(name: str) -> str:
    escaped = name.replace('"', '""')
    return f'"{escaped}"'


def first_matching_column(columns: Iterable[str], candidates: Iterable[str]) -> str | None:
    normalized_map = {normalize_column_name(column): column for column in columns}
    for candidate in candidates:
        match = normalized_map.get(normalize_column_name(candidate))
        if match is not None:
            return match
    return None


class PostgresIntrospector:
    """Small introspection wrapper around psycopg."""

    def __init__(self, dsn: str, schema: str) -> None:
        self._dsn = dsn
        self._schema = schema

    def connection(self):
        try:
            return connect(self._dsn, row_factory=dict_row)
        except Exception as exc:  # pragma: no cover - exercised in integration with a real DB
            raise RepositoryError(f"Failed to connect to PostgreSQL: {exc}") from exc

    def list_columns(self, table_name: str) -> list[str]:
        query = """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """
        with self.connection() as conn, conn.cursor() as cursor:
            cursor.execute(query, (self._schema, table_name))
            rows = cursor.fetchall()
        return [row["column_name"] for row in rows]

    def table_exists(self, table_name: str) -> bool:
        query = """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = %s AND table_name = %s
            ) AS exists
        """
        with self.connection() as conn, conn.cursor() as cursor:
            cursor.execute(query, (self._schema, table_name))
            row = cursor.fetchone()
        return bool(row and row["exists"])

    def find_table_with_columns(self, required_columns: Iterable[str]) -> str | None:
        normalized_required = {normalize_column_name(column) for column in required_columns}
        query = """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = %s
            ORDER BY table_name, ordinal_position
        """
        with self.connection() as conn, conn.cursor() as cursor:
            cursor.execute(query, (self._schema,))
            rows = cursor.fetchall()

        table_columns: dict[str, set[str]] = {}
        for row in rows:
            table_columns.setdefault(row["table_name"], set()).add(
                normalize_column_name(row["column_name"])
            )

        for table_name, columns in table_columns.items():
            if normalized_required.issubset(columns):
                return table_name
        return None


def require_columns(table_name: str, columns: list[str], required: Iterable[str]) -> None:
    missing = [column for column in required if column not in columns]
    if missing:
        rendered = ", ".join(missing)
        raise DataContractError(f"Table {table_name} is missing required columns: {rendered}")
