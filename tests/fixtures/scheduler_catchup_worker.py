"""Scheduler catch-up worker — drives the REAL scheduler, killable between
slots, for the C3 catch-up gate (13 §2.5 extended to scheduler restarts).

Like the C2 worker, this reimplements no logic: it calls the production
`Scheduler.catch_up`. The crash is injected via a dying-store wrapper
(`_KillingJobStore`) that os._exit(9)s BEFORE recording the (kill_after+1)th
slot start — a clean crash between slots, so no slot is left half-recorded.
"restart" is a fresh process running catch_up again over the same kang.db.

Usage: python scheduler_catchup_worker.py <workdir> <hours> <policy> <kill_after|none>
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from kang.adapters.fakes.audit_log import FakeAuditLog
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.job_store import SqliteJobStore, SqliteKillSwitch
from kang.adapters.sqlite.migrations import apply_migrations
from kang.kernel.audit.service import AuditService
from kang.kernel.scheduler.scheduler import Scheduler, SchedulerDeps

ANCHOR = datetime(2026, 1, 1, tzinfo=timezone.utc)
JOB_ID = "job-c3"
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class _KillingJobStore:
    """JobStore decorator that os._exit(9)s before the (kill_after+1)th
    start_run — a crash cleanly between slots (the next slot is never
    recorded, so recovery resumes from the last completed one)."""

    def __init__(self, inner: SqliteJobStore, kill_after: int | None) -> None:
        self._inner = inner
        self._kill_after = kill_after
        self._starts = 0

    def start_run(self, job_id, slot, correlation_id):
        if self._kill_after is not None and self._starts >= self._kill_after:
            os._exit(9)
        self._starts += 1
        return self._inner.start_run(job_id, slot, correlation_id)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _from_job(job_store, job_id: str, policy: str) -> None:
    from kang.domain.ports.scheduler import Job

    job_store.register_job(
        Job(
            id=job_id,
            name=job_id,
            schedule="hourly",
            catch_up=policy,
            created_at=ANCHOR,
        )
    )


def run_catch_up(
    workdir: Path, hours: int, policy: str, kill_after: int | None
) -> None:
    clock = FixedClock(ANCHOR + timedelta(hours=hours))
    conn = open_connection(workdir / "kang.db")
    real_store = SqliteJobStore(conn, clock)
    _from_job(real_store, JOB_ID, policy)
    store = _KillingJobStore(real_store, kill_after)
    scheduler = Scheduler(
        SchedulerDeps(
            clock=clock,
            job_store=store,
            kill_switch=SqliteKillSwitch(conn, clock),
            runner=lambda job, slot: None,  # no-op body; agent execution is M7
            audit=AuditService(FakeAuditLog(), clock),
            correlation_id=lambda: "corr-c3",
        )
    )
    scheduler.catch_up()


def collect(workdir: Path) -> dict:
    """Read the convergence facts: one run row per slot, outcomes, integrity."""
    conn = open_connection(workdir / "kang.db")
    try:
        rows = conn.execute(
            "SELECT started, outcome FROM job_run WHERE job_id = ? ORDER BY started",
            (JOB_ID,),
        ).fetchall()
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        quarantined = bool(
            conn.execute(
                "SELECT quarantined FROM job WHERE id = ?", (JOB_ID,)
            ).fetchone()[0]
        )
    finally:
        conn.close()
    return {
        "slots": [r[0] for r in rows],
        "outcomes": [r[1] for r in rows],
        "ok_slots": sorted(r[0] for r in rows if r[1] == "ok"),
        "integrity": integrity,
        "quarantined": quarantined,
    }


def ensure_migrated(workdir: Path) -> None:
    conn = open_connection(workdir / "kang.db")
    apply_migrations(conn, MIGRATIONS_DIR, FixedClock(ANCHOR))
    conn.close()


if __name__ == "__main__":
    directory = Path(sys.argv[1])
    hours_arg = int(sys.argv[2])
    policy_arg = sys.argv[3]
    kill = None if sys.argv[4] == "none" else int(sys.argv[4])
    run_catch_up(directory, hours_arg, policy_arg, kill)
