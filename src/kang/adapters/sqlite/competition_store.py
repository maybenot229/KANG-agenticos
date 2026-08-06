"""SqliteCompetitionStore — the competition port over kang.db.

Layer: adapters/sqlite (the only home of SQL — DB-002; no SELECT *, 11 §13).
Constitutional home: 07_DATABASE §5.2 (competition), ADR-014
(competition.created — the entity's first write path; the change-capture
trigger `create()` relies on landed in migration 0012).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from kang.domain.ports.competition_store import Competition

__all__ = ["SqliteCompetitionStore"]

_COLUMNS = (
    "id, name, url, status, evaluation, result, project_id, "
    "created_at, updated_at, device_id, revision"
)


def _moment(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _row_to_competition(row: sqlite3.Row | tuple) -> Competition:
    (
        competition_id,
        name,
        url,
        status,
        evaluation,
        result,
        project_id,
        created_at,
        updated_at,
        device_id,
        revision,
    ) = row
    return Competition(
        id=competition_id,
        name=name,
        url=url,
        status=status,
        evaluation=evaluation,
        result=result,
        project_id=project_id,
        created_at=_moment(created_at),
        updated_at=_moment(updated_at),
        device_id=device_id,
        revision=revision,
    )


class SqliteCompetitionStore:
    """CompetitionStore implementation. Writes are explicit transactions."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, competition: Competition) -> None:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                f"INSERT INTO competition ({_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    competition.id,
                    competition.name,
                    competition.url,
                    competition.status,
                    competition.evaluation,
                    competition.result,
                    competition.project_id,
                    competition.created_at.isoformat(),
                    competition.updated_at.isoformat(),
                    competition.device_id,
                    competition.revision,
                ),
            )
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

    def list_all(self) -> list[Competition]:
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM competition ORDER BY name COLLATE NOCASE, id"
        ).fetchall()
        return [_row_to_competition(row) for row in rows]
