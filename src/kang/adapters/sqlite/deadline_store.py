"""SqliteDeadlineStore — the deadline port over kang.db.

Layer: adapters/sqlite (the only home of SQL — DB-002; no SELECT *, 11 §13).
Constitutional home: 07_DATABASE §5.2 (deadline), DB-001/DB-003 (explicit
BEGIN IMMEDIATE transactions, optimistic revision checks — the revision bump
rides the checked UPDATE), §5.1 (tombstone written on delete, in the same
transaction), §4.1 (`active()` is the `v_active_deadlines` read shape).

`lead_days` is a JSON array in the column (07 §5.2) and a tuple[int, ...] in
the domain — the mapping is confined here, at the boundary, per the adapter's
translate-at-the-port-line duty (17 §4.3 rule 5).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime

from kang.domain.ports.clock import Clock
from kang.domain.ports.deadline_store import (
    Deadline,
    DeadlineNotFoundError,
    DeadlineRevisionConflictError,
)

__all__ = ["SqliteDeadlineStore"]

_COLUMNS = (
    "id, competition_id, project_id, kind, title, at, lead_days, status, "
    "created_at, updated_at, device_id, revision"
)


def _moment(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _row_to_deadline(row: sqlite3.Row | tuple) -> Deadline:
    (
        deadline_id,
        competition_id,
        project_id,
        kind,
        title,
        at,
        lead_days,
        status,
        created_at,
        updated_at,
        device_id,
        revision,
    ) = row
    return Deadline(
        id=deadline_id,
        competition_id=competition_id,
        project_id=project_id,
        kind=kind,
        title=title,
        at=at,
        lead_days=tuple(json.loads(lead_days)),
        status=status,
        created_at=_moment(created_at),
        updated_at=_moment(updated_at),
        device_id=device_id,
        revision=revision,
    )


class SqliteDeadlineStore:
    """DeadlineStore implementation. Writes are explicit transactions."""

    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self._conn = conn
        self._clock = clock

    def create(self, deadline: Deadline) -> None:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                f"INSERT INTO deadline ({_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    deadline.id,
                    deadline.competition_id,
                    deadline.project_id,
                    deadline.kind,
                    deadline.title,
                    deadline.at,
                    json.dumps(list(deadline.lead_days)),
                    deadline.status,
                    deadline.created_at.isoformat(),
                    deadline.updated_at.isoformat(),
                    deadline.device_id,
                    deadline.revision,
                ),
            )
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

    def get(self, deadline_id: str) -> Deadline:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM deadline WHERE id = ?", (deadline_id,)
        ).fetchone()
        if row is None:
            raise DeadlineNotFoundError(deadline_id)
        return _row_to_deadline(row)

    def update(self, deadline: Deadline) -> Deadline:
        now = self._clock.now()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = self._conn.execute(
                "UPDATE deadline SET competition_id = ?, project_id = ?, "
                "kind = ?, title = ?, at = ?, lead_days = ?, status = ?, "
                "updated_at = ?, revision = revision + 1 "
                "WHERE id = ? AND revision = ?",
                (
                    deadline.competition_id,
                    deadline.project_id,
                    deadline.kind,
                    deadline.title,
                    deadline.at,
                    json.dumps(list(deadline.lead_days)),
                    deadline.status,
                    now.isoformat(),
                    deadline.id,
                    deadline.revision,
                ),
            )
            if cursor.rowcount == 0:
                self._conn.execute("ROLLBACK")
                exists = self._conn.execute(
                    "SELECT revision FROM deadline WHERE id = ?", (deadline.id,)
                ).fetchone()
                if exists is None:
                    raise DeadlineNotFoundError(deadline.id)
                raise DeadlineRevisionConflictError(
                    f"deadline {deadline.id}: expected revision "
                    f"{deadline.revision}, store has {exists[0]}"
                )
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        return replace(deadline, updated_at=now, revision=deadline.revision + 1)

    def active(self) -> list[Deadline]:
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM deadline WHERE status = 'tracked' ORDER BY at, id"
        ).fetchall()
        return [_row_to_deadline(row) for row in rows]

    def delete(self, deadline_id: str, deleted_by: str) -> None:
        now = self._clock.now()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = self._conn.execute(
                "DELETE FROM deadline WHERE id = ?", (deadline_id,)
            )
            if cursor.rowcount == 0:
                self._conn.execute("ROLLBACK")
                raise DeadlineNotFoundError(deadline_id)
            self._conn.execute(
                "INSERT INTO tombstone (id, entity, deleted_at, deleted_by) "
                "VALUES (?, 'deadline', ?, ?)",
                (deadline_id, now.isoformat(), deleted_by),
            )
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
