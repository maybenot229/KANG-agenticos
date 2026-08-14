"""Transactional-approve worker — kills a real process at every real boundary
inside `held_action.approve`'s `commit_mode="transactional"` driver
(ADR-021), for the C1-style crash-kill gate this path never had.

This worker does NOT reimplement the transaction: it calls the production
`make_held_action_approve_handler` and the production `SqliteHeldActionStore`/
`SqliteJobStore`. Kill points are injected via a decorator around the real
held-action store and the real effect function — os._exit(9), no cleanup,
exactly what a crash leaves, no test seam inside production code. Mirrors
`paired_write_worker.py`'s exact shape (13 §2.5 / C2's own established
pattern), applied to a path that pattern never covered.

Usage: python transactional_approve_worker.py <workdir> <kill_at>
  kill_at in before_approve | after_approve | after_effect |
           after_mark_executed | none
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.held_action_store import SqliteHeldActionStore
from kang.adapters.sqlite.job_store import SqliteJobStore
from kang.adapters.sqlite.migrations import apply_migrations
from kang.api.dispatch import HandlerContext
from kang.api.operations.held_action_ops import make_held_action_approve_handler
from kang.domain.ports.held_action import HeldAction

KILL_POINTS = (
    "before_approve",
    "after_approve",
    "after_effect",
    "after_mark_executed",
    "none",
)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
HELD_ID = "held-crash-0000"
JOB_ID = "deadline_sweep"
ANCHOR = "2026-01-01T00:00:00+00:00"
CONTEXT = HandlerContext(
    principal="kang", correlation_id="corr-crash", trigger="cli", first_party=True
)


class _KillingHeldActionStore:
    """Decorates the real `SqliteHeldActionStore`, delegates everything
    unchanged, and os._exit(9)s at the chosen boundary inside the
    approve-flip/mark-executed pair — the two writes
    `_approve_transactional` shares one transaction across."""

    def __init__(self, inner: SqliteHeldActionStore, kill_at: str) -> None:
        self._inner = inner
        self._kill_at = kill_at

    def approve_in_txn(self, *args, **kwargs):
        if self._kill_at == "before_approve":
            os._exit(9)
        result = self._inner.approve_in_txn(*args, **kwargs)
        if self._kill_at == "after_approve":
            os._exit(9)
        return result

    def mark_executed_in_txn(self, *args, **kwargs):
        result = self._inner.mark_executed_in_txn(*args, **kwargs)
        if self._kill_at == "after_mark_executed":
            os._exit(9)
        return result

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _killing_effect(job_store: SqliteJobStore, kill_at: str):
    def effect(params: dict) -> None:
        job_store.set_enabled_in_txn(params["job_id"], False)
        if kill_at == "after_effect":
            os._exit(9)

    return effect


def _seed(workdir: Path) -> None:
    conn = open_connection(workdir / "kang.db")
    apply_migrations(conn, MIGRATIONS_DIR, FakeClock())
    conn.execute(
        "INSERT INTO job (id, name, schedule, catch_up, enabled, timeout_s, "
        "quarantined, created_at, updated_at) VALUES (?, ?, 'hourly', "
        "'run_once_latest', 1, 300, 0, ?, ?)",
        (JOB_ID, JOB_ID, ANCHOR, ANCHOR),
    )
    held = HeldAction(
        id=HELD_ID,
        operation="job.disable",
        action=f"Disable job {JOB_ID!r}",
        principal="kang",
        reason="crash-kill fixture",
        reversibility="reversible — re-enable via job.enable",
        correlation_id="corr-origin",
        created_at=ANCHOR,
        expires_at="2026-01-02T00:00:00+00:00",
        params={"job_id": JOB_ID},
    )
    SqliteHeldActionStore(conn).create(held)
    conn.commit()
    conn.close()


def run_approve(workdir: Path, kill_at: str) -> None:
    """The write path: real held_action.approve handler, transactional
    effect, on a real connection. Dies mid-flight per kill_at, or
    completes and returns normally for kill_at == 'none'."""
    _seed(workdir)
    conn = open_connection(workdir / "kang.db")
    clock = FakeClock()
    real_store = SqliteHeldActionStore(conn)
    killing_store = _KillingHeldActionStore(real_store, kill_at)
    job_store = SqliteJobStore(conn, clock)
    effects = {"job.disable": _killing_effect(job_store, kill_at)}
    handler = make_held_action_approve_handler(killing_store, clock, conn, effects)
    handler(CONTEXT, {"id": HELD_ID})
    conn.close()


def recover(workdir: Path) -> dict:
    """A fresh process's startup: open a new connection over the surviving
    file (WAL recovery on open, the same as any real restart) and inspect
    the resulting state — no bespoke recovery code exists for this path
    (ADR-001 Amendment's own claim: a crash before commit is
    indistinguishable from still-pending); this proves that claim rather
    than asserting it."""
    conn = open_connection(workdir / "kang.db")
    try:
        held_row = conn.execute(
            "SELECT status FROM held_action WHERE id = ?", (HELD_ID,)
        ).fetchone()
        job_row = conn.execute(
            "SELECT enabled FROM job WHERE id = ?", (JOB_ID,)
        ).fetchone()
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()
    return {
        "held_status": held_row[0] if held_row else None,
        "job_enabled": bool(job_row[0]) if job_row else None,
        "integrity": integrity,
    }


if __name__ == "__main__":
    directory, kill_point = Path(sys.argv[1]), sys.argv[2]
    if kill_point not in KILL_POINTS:
        raise SystemExit(f"kill_at must be one of {KILL_POINTS}")
    run_approve(directory, kill_point)
