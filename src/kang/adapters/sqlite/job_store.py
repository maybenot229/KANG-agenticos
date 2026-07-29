"""SqliteJobStore + SqliteKillSwitch — scheduler state over kang.db.

Layer: adapters/sqlite (SQL confined here — DB-002).
Constitutional home: 07_DATABASE §5.5 (job, job_run, setting), 05_AGENTS
§11 (consecutive-failure count for quarantine), 10_SECURITY D013
(kill-switch persisted in setting so a paused system stays paused).
`job_run.started` holds the SLOT time (the catch-up baseline).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from kang.domain.ports.scheduler import Job, RunOutcome

__all__ = ["KILL_SWITCH_KEY", "SqliteJobStore", "SqliteKillSwitch"]

KILL_SWITCH_KEY = "automation.paused"

_JOB_COLUMNS = (
    "id, name, schedule, catch_up, created_at, enabled, timeout_s, quarantined"
)


def _row_to_job(row: tuple) -> Job:
    return Job(
        id=row[0],
        name=row[1],
        schedule=row[2],
        catch_up=row[3],
        created_at=datetime.fromisoformat(row[4]),
        enabled=bool(row[5]),
        timeout_s=row[6],
        quarantined=bool(row[7]),
    )


class SqliteJobStore:
    """JobStore over kang.db."""

    def __init__(self, conn: sqlite3.Connection, clock) -> None:
        self._conn = conn
        self._clock = clock

    def register_job(self, job: Job) -> None:
        stamp = self._clock.now().isoformat()
        with self._writing():
            self._conn.execute(
                "INSERT INTO job (id, name, schedule, catch_up, enabled, "
                "timeout_s, quarantined, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET name = excluded.name, "
                "schedule = excluded.schedule, catch_up = excluded.catch_up, "
                "enabled = excluded.enabled, timeout_s = excluded.timeout_s, "
                "quarantined = excluded.quarantined, updated_at = excluded.updated_at",
                (
                    job.id,
                    job.name,
                    job.schedule,
                    job.catch_up,
                    int(job.enabled),
                    job.timeout_s,
                    int(job.quarantined),
                    job.created_at.isoformat(),
                    stamp,
                ),
            )

    def list_jobs(self) -> list[Job]:
        rows = self._conn.execute(
            f"SELECT {_JOB_COLUMNS} FROM job ORDER BY name"
        ).fetchall()
        return [_row_to_job(row) for row in rows]

    def last_slot(self, job_id: str) -> datetime | None:
        row = self._conn.execute(
            "SELECT MAX(started) FROM job_run WHERE job_id = ?", (job_id,)
        ).fetchone()
        return datetime.fromisoformat(row[0]) if row[0] is not None else None

    def start_run(self, job_id: str, slot: datetime, correlation_id: str) -> int:
        with self._writing():
            cursor = self._conn.execute(
                "INSERT INTO job_run (job_id, started, correlation_id) "
                "VALUES (?, ?, ?)",
                (job_id, slot.isoformat(), correlation_id),
            )
        return int(cursor.lastrowid)

    def finish_run(self, run_id: int, outcome: RunOutcome, detail: str | None) -> None:
        with self._writing():
            self._conn.execute(
                "UPDATE job_run SET finished = ?, outcome = ?, detail = ? WHERE id = ?",
                (self._clock.now().isoformat(), outcome, detail, run_id),
            )

    def record_skipped(self, job_id: str, slot: datetime) -> None:
        with self._writing():
            self._conn.execute(
                "INSERT INTO job_run (job_id, started, finished, outcome, "
                "correlation_id) VALUES (?, ?, ?, 'skipped', 'scheduler')",
                (job_id, slot.isoformat(), slot.isoformat()),
            )

    def consecutive_failures(self, job_id: str) -> int:
        rows = self._conn.execute(
            "SELECT outcome FROM job_run WHERE job_id = ? AND outcome IS NOT NULL "
            "ORDER BY id DESC",
            (job_id,),
        ).fetchall()
        count = 0
        for (outcome,) in rows:
            if outcome in ("failed", "timeout"):
                count += 1
            else:
                break
        return count

    def set_quarantined(self, job_id: str, quarantined: bool) -> None:
        with self._writing():
            self._conn.execute(
                "UPDATE job SET quarantined = ? WHERE id = ?",
                (int(quarantined), job_id),
            )

    def recover_incomplete(self, now: datetime) -> int:
        with self._writing():
            cursor = self._conn.execute(
                "UPDATE job_run SET finished = ?, outcome = 'failed' "
                "WHERE finished IS NULL",
                (now.isoformat(),),
            )
        return cursor.rowcount

    def _writing(self):
        return _Transaction(self._conn)


class SqliteKillSwitch:
    """KillSwitch persisted in setting (07 §5.5)."""

    def __init__(self, conn: sqlite3.Connection, clock) -> None:
        self._conn = conn
        self._clock = clock

    def is_engaged(self) -> bool:
        row = self._conn.execute(
            "SELECT value FROM setting WHERE key = ?", (KILL_SWITCH_KEY,)
        ).fetchone()
        return row is not None and row[0] == "1"

    def engage(self, reason: str) -> None:
        self._set("1", reason)

    def disengage(self) -> None:
        self._set("0", "")

    def _set(self, value: str, reason: str) -> None:
        with _Transaction(self._conn):
            self._conn.execute(
                "INSERT INTO setting (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at",
                (KILL_SWITCH_KEY, value, self._clock.now().isoformat()),
            )


class _Transaction:
    """BEGIN IMMEDIATE / COMMIT-or-ROLLBACK context (DB-001/DB-003)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __enter__(self) -> None:
        self._conn.execute("BEGIN IMMEDIATE")

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self._conn.execute("COMMIT")
        elif self._conn.in_transaction:
            self._conn.execute("ROLLBACK")
