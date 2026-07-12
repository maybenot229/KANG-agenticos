"""SqliteTaskStore — the task port over kang.db.

Layer: adapters/sqlite (the only home of SQL — DB-002; no SELECT *, 11 §13).
Constitutional home: 07_DATABASE §5.2 (task), DB-001/DB-003 (explicit
BEGIN IMMEDIATE transactions, optimistic revision checks — the revision
bump rides the checked UPDATE), §5.1 (tombstone written on delete, in the
same transaction).
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime

from kang.domain.ports.clock import Clock
from kang.domain.ports.task_store import (
    RevisionConflictError,
    Task,
    TaskNotFoundError,
)

__all__ = ["SqliteTaskStore"]

_COLUMNS = (
    "id, project_id, title, notes, status, priority, due, plan_date, "
    "estimate_min, actual_min, completed_at, created_at, updated_at, "
    "device_id, revision"
)


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment is not None else None


def _moment(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text is not None else None


def _row_to_task(row: sqlite3.Row | tuple) -> Task:
    (
        task_id,
        project_id,
        title,
        notes,
        status,
        priority,
        due,
        plan_date,
        estimate_min,
        actual_min,
        completed_at,
        created_at,
        updated_at,
        device_id,
        revision,
    ) = row
    return Task(
        id=task_id,
        project_id=project_id,
        title=title,
        notes=notes,
        status=status,
        priority=priority,
        due=due,
        plan_date=plan_date,
        estimate_min=estimate_min,
        actual_min=actual_min,
        completed_at=_moment(completed_at),
        created_at=_moment(created_at),  # type: ignore[arg-type]
        updated_at=_moment(updated_at),  # type: ignore[arg-type]
        device_id=device_id,
        revision=revision,
    )


class SqliteTaskStore:
    """TaskStore implementation. Writes are explicit transactions."""

    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self._conn = conn
        self._clock = clock

    def create(self, task: Task) -> None:
        with_transaction = self._conn
        with_transaction.execute("BEGIN IMMEDIATE")
        try:
            with_transaction.execute(
                f"INSERT INTO task ({_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task.id,
                    task.project_id,
                    task.title,
                    task.notes,
                    task.status,
                    task.priority,
                    task.due,
                    task.plan_date,
                    task.estimate_min,
                    task.actual_min,
                    _iso(task.completed_at),
                    _iso(task.created_at),
                    _iso(task.updated_at),
                    task.device_id,
                    task.revision,
                ),
            )
            with_transaction.execute("COMMIT")
        except sqlite3.Error:
            with_transaction.execute("ROLLBACK")
            raise

    def get(self, task_id: str) -> Task:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM task WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise TaskNotFoundError(task_id)
        return _row_to_task(row)

    def update(self, task: Task) -> Task:
        now = self._clock.now()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = self._conn.execute(
                "UPDATE task SET project_id = ?, title = ?, notes = ?, "
                "status = ?, priority = ?, due = ?, plan_date = ?, "
                "estimate_min = ?, actual_min = ?, completed_at = ?, "
                "updated_at = ?, revision = revision + 1 "
                "WHERE id = ? AND revision = ?",
                (
                    task.project_id,
                    task.title,
                    task.notes,
                    task.status,
                    task.priority,
                    task.due,
                    task.plan_date,
                    task.estimate_min,
                    task.actual_min,
                    _iso(task.completed_at),
                    now.isoformat(),
                    task.id,
                    task.revision,
                ),
            )
            if cursor.rowcount == 0:
                self._conn.execute("ROLLBACK")
                exists = self._conn.execute(
                    "SELECT revision FROM task WHERE id = ?", (task.id,)
                ).fetchone()
                if exists is None:
                    raise TaskNotFoundError(task.id)
                raise RevisionConflictError(
                    f"task {task.id}: expected revision {task.revision}, "
                    f"store has {exists[0]}"
                )
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        return replace(task, updated_at=now, revision=task.revision + 1)

    def delete(self, task_id: str, deleted_by: str) -> None:
        now = self._clock.now()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = self._conn.execute("DELETE FROM task WHERE id = ?", (task_id,))
            if cursor.rowcount == 0:
                self._conn.execute("ROLLBACK")
                raise TaskNotFoundError(task_id)
            self._conn.execute(
                "INSERT INTO tombstone (id, entity, deleted_at, deleted_by) "
                "VALUES (?, 'task', ?, ?)",
                (task_id, now.isoformat(), deleted_by),
            )
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
