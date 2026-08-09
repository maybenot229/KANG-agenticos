"""SqliteGoalStore — the goal port over kang.db.

Layer: adapters/sqlite (the only home of SQL — DB-002; no SELECT *, 11 §13).
Constitutional home: 07_DATABASE §5.2 (goal), ADR-016 (goal.created — the
entity's first write path; the change-capture trigger `create()` relies
on landed in migration 0014), ADR-018 (`get`/`update` — the entity's
first status transitions).
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime

from kang.domain.ports.clock import Clock
from kang.domain.ports.goal_store import (
    Goal,
    GoalNotFoundError,
    GoalRevisionConflictError,
)

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

    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self._conn = conn
        self._clock = clock

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

    def get(self, goal_id: str) -> Goal:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM goal WHERE id = ?", (goal_id,)
        ).fetchone()
        if row is None:
            raise GoalNotFoundError(goal_id)
        return _row_to_goal(row)

    def update(self, goal: Goal) -> Goal:
        now = self._clock.now()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = self._conn.execute(
                "UPDATE goal SET title = ?, description = ?, horizon = ?, "
                "status = ?, updated_at = ?, revision = revision + 1 "
                "WHERE id = ? AND revision = ?",
                (
                    goal.title,
                    goal.description,
                    goal.horizon,
                    goal.status,
                    now.isoformat(),
                    goal.id,
                    goal.revision,
                ),
            )
            if cursor.rowcount == 0:
                self._conn.execute("ROLLBACK")
                exists = self._conn.execute(
                    "SELECT revision FROM goal WHERE id = ?", (goal.id,)
                ).fetchone()
                if exists is None:
                    raise GoalNotFoundError(goal.id)
                raise GoalRevisionConflictError(
                    f"goal {goal.id}: expected revision {goal.revision}, "
                    f"store has {exists[0]}"
                )
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        return replace(goal, updated_at=now, revision=goal.revision + 1)

    def list_all(self) -> list[Goal]:
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM goal ORDER BY title COLLATE NOCASE, id"
        ).fetchall()
        return [_row_to_goal(row) for row in rows]
