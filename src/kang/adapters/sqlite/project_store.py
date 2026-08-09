"""SqliteProjectStore — the project port over kang.db.

Layer: adapters/sqlite (the only home of SQL — DB-002; no SELECT *, 11 §13).
Constitutional home: 07_DATABASE §5.2 (project), ADR-013 (project.created —
the entity's first write path; the change-capture trigger `create()`
relies on landed in migration 0011), ADR-018 (`get`/`update` — the
entity's first status transition, `complete`).
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime

from kang.domain.ports.clock import Clock
from kang.domain.ports.project_store import (
    Project,
    ProjectNotFoundError,
    ProjectRevisionConflictError,
)

__all__ = ["SqliteProjectStore"]

_COLUMNS = (
    "id, name, description, status, vault_folder, github_repo, goal_id, "
    "created_at, updated_at, device_id, revision"
)


def _moment(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _row_to_project(row: sqlite3.Row | tuple) -> Project:
    (
        project_id,
        name,
        description,
        status,
        vault_folder,
        github_repo,
        goal_id,
        created_at,
        updated_at,
        device_id,
        revision,
    ) = row
    return Project(
        id=project_id,
        name=name,
        description=description,
        status=status,
        vault_folder=vault_folder,
        github_repo=github_repo,
        goal_id=goal_id,
        created_at=_moment(created_at),
        updated_at=_moment(updated_at),
        device_id=device_id,
        revision=revision,
    )


class SqliteProjectStore:
    """ProjectStore implementation. Writes are explicit transactions."""

    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self._conn = conn
        self._clock = clock

    def create(self, project: Project) -> None:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                f"INSERT INTO project ({_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    project.id,
                    project.name,
                    project.description,
                    project.status,
                    project.vault_folder,
                    project.github_repo,
                    project.goal_id,
                    project.created_at.isoformat(),
                    project.updated_at.isoformat(),
                    project.device_id,
                    project.revision,
                ),
            )
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

    def get(self, project_id: str) -> Project:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM project WHERE id = ?", (project_id,)
        ).fetchone()
        if row is None:
            raise ProjectNotFoundError(project_id)
        return _row_to_project(row)

    def update(self, project: Project) -> Project:
        now = self._clock.now()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = self._conn.execute(
                "UPDATE project SET name = ?, description = ?, status = ?, "
                "vault_folder = ?, github_repo = ?, goal_id = ?, "
                "updated_at = ?, revision = revision + 1 "
                "WHERE id = ? AND revision = ?",
                (
                    project.name,
                    project.description,
                    project.status,
                    project.vault_folder,
                    project.github_repo,
                    project.goal_id,
                    now.isoformat(),
                    project.id,
                    project.revision,
                ),
            )
            if cursor.rowcount == 0:
                self._conn.execute("ROLLBACK")
                exists = self._conn.execute(
                    "SELECT revision FROM project WHERE id = ?", (project.id,)
                ).fetchone()
                if exists is None:
                    raise ProjectNotFoundError(project.id)
                raise ProjectRevisionConflictError(
                    f"project {project.id}: expected revision "
                    f"{project.revision}, store has {exists[0]}"
                )
            self._conn.execute("COMMIT")
        except sqlite3.Error:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        return replace(project, updated_at=now, revision=project.revision + 1)

    def list_all(self) -> list[Project]:
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM project ORDER BY name COLLATE NOCASE, id"
        ).fetchall()
        return [_row_to_project(row) for row in rows]
