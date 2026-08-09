"""SqliteGoalStore — the goal port over kang.db.

Layer: adapters/sqlite (the only home of SQL — DB-002; no SELECT *, 11 §13).
Constitutional home: 07_DATABASE §5.2 (goal), ADR-016 (goal.created — the
entity's first write path; the change-capture trigger `create()` relies
on landed in migration 0014).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from kang.domain.ports.goal_store import Goal

__all__ = ["SqliteGoalStore"]

_COLUMNS = (
    "id, title, description, horizon, status, created_at, updated_at, "
    "device_id, revision"
)


def _moment(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _row_to_goal(row: sqlite3.Row | tuple) -> Goal:
    (
        goal_id,
        title,
        description,
        horizon,
        status,
        created_at,
        updated_at,
        device_id,
        revision,
    ) = row
    return Goal(
        id=goal_id,
        title=title,
        description=description,
        horizon=horizon,
        status=status,
        created_at=_moment(created_at),
        updated_at=_moment(updated_at),
        device_id=device_id,
        revision=revision,
    )


class SqliteGoalStore:
    """GoalStore implementation. Writes are explicit transactions."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, goal: Goal) -> None:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                f"INSERT INTO goal ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    goal.id,
                    goal.title,
                    goal.description,
                    goal.horizon,
                    goal.status,
                    goal.created_at.isoformat(),
                    goal.updated_at.isoformat(),
                    goal.device_id,
                    goal.revision,
                ),
            )
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

    def list_all(self) -> list[Goal]:
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM goal ORDER BY title COLLATE NOCASE, id"
        ).fetchall()
        return [_row_to_goal(row) for row in rows]
