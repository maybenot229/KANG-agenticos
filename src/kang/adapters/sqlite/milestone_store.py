"""SqliteMilestoneStore — the milestone port over kang.db.

Layer: adapters/sqlite (the only home of SQL — DB-002; no SELECT *, 11 §13).
Constitutional home: 07_DATABASE §5.2 (milestone), ADR-015
(milestone.created — the entity's first write path; the change-capture
trigger `create()` relies on landed in migration 0013), ADR-018
(`get`/`update` — the entity's first status transitions; the SQL mirrors
`SqliteTaskStore.update()`'s exact optimistic-concurrency shape).
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime

from kang.domain.ports.clock import Clock
from kang.domain.ports.milestone_store import (
    Milestone,
    MilestoneNotFoundError,
    MilestoneRevisionConflictError,
)

__all__ = ["SqliteMilestoneStore"]

_COLUMNS = (
    "id, project_id, title, due, status, created_at, updated_at, device_id, revision"
)


def _moment(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _row_to_milestone(row: sqlite3.Row | tuple) -> Milestone:
    (
        milestone_id,
        project_id,
        title,
        due,
        status,
        created_at,
        updated_at,
        device_id,
        revision,
    ) = row
    return Milestone(
        id=milestone_id,
        project_id=project_id,
        title=title,
        due=due,
        status=status,
        created_at=_moment(created_at),
        updated_at=_moment(updated_at),
        device_id=device_id,
        revision=revision,
    )


class SqliteMilestoneStore:
    """MilestoneStore implementation. Writes are explicit transactions."""

    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self._conn = conn
        self._clock = clock

    def create(self, milestone: Milestone) -> None:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                f"INSERT INTO milestone ({_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    milestone.id,
                    milestone.project_id,
                    milestone.title,
                    milestone.due,
                    milestone.status,
                    milestone.created_at.isoformat(),
                    milestone.updated_at.isoformat(),
                    milestone.device_id,
                    milestone.revision,
                ),
            )
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

    def get(self, milestone_id: str) -> Milestone:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM milestone WHERE id = ?", (milestone_id,)
        ).fetchone()
        if row is None:
            raise MilestoneNotFoundError(milestone_id)
        return _row_to_milestone(row)

    def update(self, milestone: Milestone) -> Milestone:
        now = self._clock.now()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = self._conn.execute(
                "UPDATE milestone SET project_id = ?, title = ?, due = ?, "
                "status = ?, updated_at = ?, revision = revision + 1 "
                "WHERE id = ? AND revision = ?",
                (
                    milestone.project_id,
                    milestone.title,
                    milestone.due,
                    milestone.status,
                    now.isoformat(),
                    milestone.id,
                    milestone.revision,
                ),
            )
            if cursor.rowcount == 0:
                self._conn.execute("ROLLBACK")
                exists = self._conn.execute(
                    "SELECT revision FROM milestone WHERE id = ?", (milestone.id,)
                ).fetchone()
                if exists is None:
                    raise MilestoneNotFoundError(milestone.id)
                raise MilestoneRevisionConflictError(
                    f"milestone {milestone.id}: expected revision "
                    f"{milestone.revision}, store has {exists[0]}"
                )
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        return replace(milestone, updated_at=now, revision=milestone.revision + 1)

    def list_for_project(self, project_id: str) -> list[Milestone]:
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM milestone WHERE project_id = ? "
            "ORDER BY due IS NULL, due, id",
            (project_id,),
        ).fetchall()
        return [_row_to_milestone(row) for row in rows]
