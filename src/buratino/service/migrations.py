"""Simple SQL migration runner for buratino runtime tables."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from psycopg import connect

from buratino.models.errors import RepositoryError


@dataclass(frozen=True)
class MigrationRunner:
    dsn: str
    migrations_dir: Path

    def run(self) -> list[str]:
        if not self.migrations_dir.exists():
            return []
        applied: list[str] = []
        try:
            with connect(self.dsn) as conn:
                for path in sorted(self.migrations_dir.glob("*.sql")):
                    conn.execute(path.read_text(encoding="utf-8"))
                    applied.append(path.name)
                conn.commit()
        except Exception as exc:  # pragma: no cover
            raise RepositoryError(f"Failed to apply migrations: {exc}") from exc
        return applied
