"""Recovery re-application — recovery-grade events applied to kang.db.

Layer: adapters/sqlite (re-application is SQL; SQL lives here — DB-002).
Constitutional home: 15_EVENT_BUS EB-003 ("Re-application MUST be
idempotent: the state write is keyed by entity id + revision; re-applying
a committed change is a no-op"), EB-009 forms 1-2 (crash redo, snapshot
gap-fill). This module re-applies and reports; it never decides (15 §4's
containment rule). It takes envelopes as data — it MUST NOT import the
eventlog adapter (17 §4.3.6); composition happens above the port line.

Supported types grow with the event registry (M2); at M1 the task entity
carries the proof.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from kang.domain.ports.eventlog import EventEnvelope

__all__ = ["ReapplyOutcome", "RecoveryError", "apply_recovery_event"]

_TASK_FIELDS = (
    "id",
    "project_id",
    "title",
    "notes",
    "status",
    "priority",
    "due",
    "plan_date",
    "estimate_min",
    "actual_min",
    "completed_at",
    "created_at",
    "updated_at",
    "device_id",
    "revision",
)


class RecoveryError(Exception):
    """The event cannot be re-applied. Loud, never half-applied (07 F3)."""


@dataclass(frozen=True)
class ReapplyOutcome:
    """What re-application did: 'applied' | 'noop' (already committed)."""

    event_id: str
    outcome: str


def _payload_task_row(envelope: EventEnvelope) -> tuple:
    payload = envelope.payload
    missing = [f for f in _TASK_FIELDS if f not in payload]
    if missing:
        raise RecoveryError(
            f"recovery-grade payload for {envelope.type} is not "
            f"self-sufficient (EB-003): missing {missing}"
        )
    return tuple(payload[f] for f in _TASK_FIELDS)


def _apply_task_upsert(conn: sqlite3.Connection, envelope: EventEnvelope) -> str:
    row = _payload_task_row(envelope)
    task_id, revision = row[0], row[-1]
    current = conn.execute(
        "SELECT revision FROM task WHERE id = ?", (task_id,)
    ).fetchone()
    if current is not None and current[0] >= revision:
        return "noop"  # already committed — idempotent by id + revision
    conn.execute("BEGIN IMMEDIATE")
    try:
        if current is None:
            conn.execute(
                "INSERT INTO task (id, project_id, title, notes, status, "
                "priority, due, plan_date, estimate_min, actual_min, "
                "completed_at, created_at, updated_at, device_id, revision) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )
        else:
            conn.execute(
                "UPDATE task SET project_id = ?, title = ?, notes = ?, "
                "status = ?, priority = ?, due = ?, plan_date = ?, "
                "estimate_min = ?, actual_min = ?, completed_at = ?, "
                "created_at = ?, updated_at = ?, device_id = ?, revision = ? "
                "WHERE id = ?",
                row[1:] + (task_id,),
            )
        conn.execute("COMMIT")
    except sqlite3.Error:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    return "applied"


_APPLIERS = {
    "task.created": _apply_task_upsert,
    "task.updated": _apply_task_upsert,
}


def apply_recovery_event(
    conn: sqlite3.Connection, envelope: EventEnvelope
) -> ReapplyOutcome:
    """Idempotently re-apply one recovery-grade event to kang.db."""
    if not envelope.recovery_grade:
        raise RecoveryError(
            f"{envelope.type} is not recovery-grade; nothing to re-apply"
        )
    applier = _APPLIERS.get(envelope.type)
    if applier is None:
        raise RecoveryError(
            f"no re-application path for {envelope.type} — a recovery-grade "
            "type without an applier is a registry defect (EB-006 §6.3)"
        )
    return ReapplyOutcome(event_id=envelope.event_id, outcome=applier(conn, envelope))
