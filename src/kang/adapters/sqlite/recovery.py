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

import json
import sqlite3

from kang.domain.ports.eventlog import EventEnvelope
from kang.domain.ports.recovery import ReapplyOutcome, RecoveryError

__all__ = [
    "ReapplyOutcome",
    "RecoveryError",
    "SqliteRecoveryApplier",
    "apply_recovery_event",
]

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


# RecoveryError / ReapplyOutcome are defined by the port (domain/ports/
# recovery.py) and imported above — one datatype, owned by the interface.

# Entity kinds this adapter can answer existence for (the orphan decision,
# §4.3). Grows with the schema; unknown kinds are a registry defect, loud.
_EXISTS_TABLE = {
    "task": "task",
    "deadline": "deadline",
    "project": "project",
    "competition": "competition",
    "milestone": "milestone",
    "goal": "goal",
}

_DEADLINE_FIELDS = (
    "id",
    "competition_id",
    "project_id",
    "kind",
    "title",
    "at",
    "lead_days",
    "status",
    "created_at",
    "updated_at",
    "device_id",
    "revision",
)

_PROJECT_FIELDS = (
    "id",
    "name",
    "description",
    "status",
    "vault_folder",
    "github_repo",
    "goal_id",
    "created_at",
    "updated_at",
    "device_id",
    "revision",
)

_COMPETITION_FIELDS = (
    "id",
    "name",
    "url",
    "status",
    "evaluation",
    "result",
    "project_id",
    "created_at",
    "updated_at",
    "device_id",
    "revision",
)

_MILESTONE_FIELDS = (
    "id",
    "project_id",
    "title",
    "due",
    "status",
    "created_at",
    "updated_at",
    "device_id",
    "revision",
)

_GOAL_FIELDS = (
    "id",
    "title",
    "description",
    "horizon",
    "status",
    "created_at",
    "updated_at",
    "device_id",
    "revision",
)


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


def _payload_deadline_row(envelope: EventEnvelope) -> tuple:
    payload = envelope.payload
    missing = [f for f in _DEADLINE_FIELDS if f not in payload]
    if missing:
        raise RecoveryError(
            f"recovery-grade payload for {envelope.type} is not "
            f"self-sufficient (EB-003): missing {missing}"
        )
    # `lead_days` crosses the port line as a JSON array and lands in the
    # column as JSON text — the same translation SqliteDeadlineStore does
    # (17 §4.3.5: adapters translate at the boundary).
    return tuple(
        json.dumps(payload[f]) if f == "lead_days" else payload[f]
        for f in _DEADLINE_FIELDS
    )


def _apply_deadline_upsert(conn: sqlite3.Connection, envelope: EventEnvelope) -> str:
    row = _payload_deadline_row(envelope)
    deadline_id, revision = row[0], row[-1]
    current = conn.execute(
        "SELECT revision FROM deadline WHERE id = ?", (deadline_id,)
    ).fetchone()
    if current is not None and current[0] >= revision:
        return "noop"  # already committed — idempotent by id + revision
    conn.execute("BEGIN IMMEDIATE")
    try:
        if current is None:
            conn.execute(
                "INSERT INTO deadline (id, competition_id, project_id, kind, "
                "title, at, lead_days, status, created_at, updated_at, "
                "device_id, revision) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )
        else:
            conn.execute(
                "UPDATE deadline SET competition_id = ?, project_id = ?, "
                "kind = ?, title = ?, at = ?, lead_days = ?, status = ?, "
                "created_at = ?, updated_at = ?, device_id = ?, revision = ? "
                "WHERE id = ?",
                row[1:] + (deadline_id,),
            )
        conn.execute("COMMIT")
    except sqlite3.Error:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    return "applied"


def _payload_project_row(envelope: EventEnvelope) -> tuple:
    payload = envelope.payload
    missing = [f for f in _PROJECT_FIELDS if f not in payload]
    if missing:
        raise RecoveryError(
            f"recovery-grade payload for {envelope.type} is not "
            f"self-sufficient (EB-003): missing {missing}"
        )
    return tuple(payload[f] for f in _PROJECT_FIELDS)


def _apply_project_upsert(conn: sqlite3.Connection, envelope: EventEnvelope) -> str:
    row = _payload_project_row(envelope)
    project_id, revision = row[0], row[-1]
    current = conn.execute(
        "SELECT revision FROM project WHERE id = ?", (project_id,)
    ).fetchone()
    if current is not None and current[0] >= revision:
        return "noop"  # already committed — idempotent by id + revision
    conn.execute("BEGIN IMMEDIATE")
    try:
        if current is None:
            conn.execute(
                "INSERT INTO project (id, name, description, status, "
                "vault_folder, github_repo, goal_id, created_at, updated_at, "
                "device_id, revision) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )
        else:
            conn.execute(
                "UPDATE project SET name = ?, description = ?, status = ?, "
                "vault_folder = ?, github_repo = ?, goal_id = ?, "
                "created_at = ?, updated_at = ?, device_id = ?, revision = ? "
                "WHERE id = ?",
                row[1:] + (project_id,),
            )
        conn.execute("COMMIT")
    except sqlite3.Error:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    return "applied"


def _payload_competition_row(envelope: EventEnvelope) -> tuple:
    payload = envelope.payload
    missing = [f for f in _COMPETITION_FIELDS if f not in payload]
    if missing:
        raise RecoveryError(
            f"recovery-grade payload for {envelope.type} is not "
            f"self-sufficient (EB-003): missing {missing}"
        )
    return tuple(payload[f] for f in _COMPETITION_FIELDS)


def _apply_competition_upsert(conn: sqlite3.Connection, envelope: EventEnvelope) -> str:
    row = _payload_competition_row(envelope)
    competition_id, revision = row[0], row[-1]
    current = conn.execute(
        "SELECT revision FROM competition WHERE id = ?", (competition_id,)
    ).fetchone()
    if current is not None and current[0] >= revision:
        return "noop"  # already committed — idempotent by id + revision
    conn.execute("BEGIN IMMEDIATE")
    try:
        if current is None:
            conn.execute(
                "INSERT INTO competition (id, name, url, status, evaluation, "
                "result, project_id, created_at, updated_at, device_id, "
                "revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )
        else:
            conn.execute(
                "UPDATE competition SET name = ?, url = ?, status = ?, "
                "evaluation = ?, result = ?, project_id = ?, created_at = ?, "
                "updated_at = ?, device_id = ?, revision = ? WHERE id = ?",
                row[1:] + (competition_id,),
            )
        conn.execute("COMMIT")
    except sqlite3.Error:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    return "applied"


def _payload_milestone_row(envelope: EventEnvelope) -> tuple:
    payload = envelope.payload
    missing = [f for f in _MILESTONE_FIELDS if f not in payload]
    if missing:
        raise RecoveryError(
            f"recovery-grade payload for {envelope.type} is not "
            f"self-sufficient (EB-003): missing {missing}"
        )
    return tuple(payload[f] for f in _MILESTONE_FIELDS)


def _apply_milestone_upsert(conn: sqlite3.Connection, envelope: EventEnvelope) -> str:
    row = _payload_milestone_row(envelope)
    milestone_id, revision = row[0], row[-1]
    current = conn.execute(
        "SELECT revision FROM milestone WHERE id = ?", (milestone_id,)
    ).fetchone()
    if current is not None and current[0] >= revision:
        return "noop"  # already committed — idempotent by id + revision
    conn.execute("BEGIN IMMEDIATE")
    try:
        if current is None:
            conn.execute(
                "INSERT INTO milestone (id, project_id, title, due, status, "
                "created_at, updated_at, device_id, revision) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )
        else:
            conn.execute(
                "UPDATE milestone SET project_id = ?, title = ?, due = ?, "
                "status = ?, created_at = ?, updated_at = ?, device_id = ?, "
                "revision = ? WHERE id = ?",
                row[1:] + (milestone_id,),
            )
        conn.execute("COMMIT")
    except sqlite3.Error:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    return "applied"


def _payload_goal_row(envelope: EventEnvelope) -> tuple:
    payload = envelope.payload
    missing = [f for f in _GOAL_FIELDS if f not in payload]
    if missing:
        raise RecoveryError(
            f"recovery-grade payload for {envelope.type} is not "
            f"self-sufficient (EB-003): missing {missing}"
        )
    return tuple(payload[f] for f in _GOAL_FIELDS)


def _apply_goal_upsert(conn: sqlite3.Connection, envelope: EventEnvelope) -> str:
    row = _payload_goal_row(envelope)
    goal_id, revision = row[0], row[-1]
    current = conn.execute(
        "SELECT revision FROM goal WHERE id = ?", (goal_id,)
    ).fetchone()
    if current is not None and current[0] >= revision:
        return "noop"  # already committed — idempotent by id + revision
    conn.execute("BEGIN IMMEDIATE")
    try:
        if current is None:
            conn.execute(
                "INSERT INTO goal (id, title, description, horizon, status, "
                "created_at, updated_at, device_id, revision) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )
        else:
            conn.execute(
                "UPDATE goal SET title = ?, description = ?, horizon = ?, "
                "status = ?, created_at = ?, updated_at = ?, device_id = ?, "
                "revision = ? WHERE id = ?",
                row[1:] + (goal_id,),
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
    # ADR-004: a recovery-grade type without an applier is a registry defect
    # (EB-006 §6.3), so registering deadline.created/updated obliges these.
    "deadline.created": _apply_deadline_upsert,
    "deadline.updated": _apply_deadline_upsert,
    # ADR-013: project.created's own obligation, same reasoning.
    "project.created": _apply_project_upsert,
    # ADR-014: competition.created's own obligation, same reasoning.
    "competition.created": _apply_competition_upsert,
    # ADR-015: milestone.created's own obligation, same reasoning.
    "milestone.created": _apply_milestone_upsert,
    # ADR-016: goal.created's own obligation, same reasoning.
    "goal.created": _apply_goal_upsert,
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


class SqliteRecoveryApplier:
    """RecoveryApplier over kang.db — the port the caged reconciliation
    module depends on, keeping reconciliation adapter-free (17 §4.3)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def reapply(self, envelope: EventEnvelope) -> ReapplyOutcome:
        return apply_recovery_event(self._conn, envelope)

    def entity_exists(self, kind: str, entity_id: str) -> bool:
        table = _EXISTS_TABLE.get(kind)
        if table is None:
            raise RecoveryError(
                f"no existence check for entity kind {kind!r} — an entity "
                "ref the reconciler cannot verify is a registry defect (§4.3)"
            )
        row = self._conn.execute(
            f"SELECT 1 FROM {table} WHERE id = ?", (entity_id,)
        ).fetchone()
        return row is not None
