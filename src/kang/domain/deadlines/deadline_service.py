"""Deadline domain service — invariants and transitions for the deadline
entity.

Layer: domain/deadlines (capability service; deterministic, zero I/O).
Constitutional home: 02_PRD FR-030/FR-031; 07_DATABASE §5.2 (kinds,
statuses, the `lead_days` alert schedule, and the CHECK requiring a
competition, a project, or a self-standing kind); 05_AGENTS Appendix A
(deadline_sweep is mechanical — pure SQL plus this module, no model calls,
which is why its failure is itself critical-alerted); 17 §6.1.

Time arithmetic is done against a caller-supplied `now`, never a wall clock
read here (11 §14: injected time, so the sweep is replayable and the
determinism suite can pin it).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from kang.domain.ports.clock import Clock
from kang.domain.ports.deadline_store import (
    DEADLINE_KINDS,
    DEFAULT_LEAD_DAYS,
    Deadline,
)

__all__ = [
    "DeadlineDraft",
    "DeadlineValidationError",
    "create_deadline",
    "deadline_event_payload",
    "due_lead_thresholds",
    "mark_alerted",
    "mark_met",
    "mark_missed",
]

# Kinds that stand alone: every other kind must hang off a competition or a
# project (07 §5.2's table-level CHECK, enforced here too so the violation is
# a typed domain error before it is an sqlite IntegrityError).
_SELF_STANDING_KINDS = ("school", "custom")


class DeadlineValidationError(Exception):
    """A deadline invariant was violated. Raised before anything is
    persisted."""


@dataclass(frozen=True)
class DeadlineDraft:
    """What Kang (or an importer) states about a new deadline; the system
    stamps the rest (11 §4: beyond four parameters, it's a dataclass)."""

    title: str
    at: str
    kind: str = "custom"
    competition_id: str | None = None
    project_id: str | None = None
    lead_days: tuple[int, ...] = DEFAULT_LEAD_DAYS


def _parse_at(at: str) -> datetime:
    """Parse a deadline instant, or raise the domain's own error — never let
    a ValueError from the stdlib escape as an untyped failure (11 §9)."""
    try:
        return datetime.fromisoformat(at)
    except ValueError as exc:
        raise DeadlineValidationError(
            f"deadline `at` must be ISO-8601, got {at!r}"
        ) from exc


def _validate(draft: DeadlineDraft) -> None:
    if not draft.title.strip():
        raise DeadlineValidationError("title must be non-empty")
    if draft.kind not in DEADLINE_KINDS:
        raise DeadlineValidationError(f"kind must be one of {DEADLINE_KINDS}")
    _parse_at(draft.at)
    if any(days < 0 for days in draft.lead_days):
        raise DeadlineValidationError("lead_days must all be non-negative")
    if len(set(draft.lead_days)) != len(draft.lead_days):
        raise DeadlineValidationError("lead_days must not repeat a threshold")
    anchored = draft.competition_id is not None or draft.project_id is not None
    if not anchored and draft.kind not in _SELF_STANDING_KINDS:
        raise DeadlineValidationError(
            f"a {draft.kind!r} deadline must reference a competition or a "
            f"project; only {_SELF_STANDING_KINDS} stand alone (07 §5.2)"
        )


def create_deadline(
    draft: DeadlineDraft, deadline_id: str, clock: Clock, device_id: str
) -> Deadline:
    """Build a valid new Deadline with the sync quartet stamped (D009):
    created_at/updated_at from the injected clock, device_id, revision 1.
    Lead thresholds are stored descending so the sweep's first match is the
    earliest warning (determinism: one canonical order, 13 §2.6)."""
    _validate(draft)
    now = clock.now()
    return Deadline(
        id=deadline_id,
        kind=draft.kind,
        title=draft.title,
        at=draft.at,
        status="tracked",
        competition_id=draft.competition_id,
        project_id=draft.project_id,
        lead_days=tuple(sorted(draft.lead_days, reverse=True)),
        created_at=now,
        updated_at=now,
        device_id=device_id,
        revision=1,
    )


def due_lead_thresholds(deadline: Deadline, now: datetime) -> tuple[int, ...]:
    """Which lead thresholds have been crossed as of `now`, descending.

    A threshold of N days is crossed once `now` is within N days of `at`.
    Returns every crossed threshold rather than just the nearest, so the
    caller can tell a first alert from a later, more urgent one; an empty
    tuple means nothing is due yet. A deadline already past `at` has crossed
    all of them.

    Pure: no clock read, no store access — the sweep supplies `now`, which
    is what lets a simulated week replay identically (13 §2.6).
    """
    remaining = _parse_at(deadline.at) - now
    remaining_days = remaining.total_seconds() / 86400
    return tuple(days for days in deadline.lead_days if remaining_days <= days)


def mark_alerted(deadline: Deadline) -> Deadline:
    """`tracked → alerted`: the sweep has surfaced this deadline at least
    once. The scope `deadlines.mark_alerted` (05 §9) exists precisely so
    this transition is the only write the sweep holds."""
    if deadline.status != "tracked":
        raise DeadlineValidationError(
            f"deadline {deadline.id} is {deadline.status}, not tracked"
        )
    return replace(deadline, status="alerted")


def mark_met(deadline: Deadline) -> Deadline:
    """`tracked | alerted → met`: Kang made it."""
    if deadline.status not in ("tracked", "alerted"):
        raise DeadlineValidationError(
            f"deadline {deadline.id} is {deadline.status}; only a tracked or "
            "alerted deadline can be met"
        )
    return replace(deadline, status="met")


def mark_missed(deadline: Deadline) -> Deadline:
    """`tracked | alerted → missed`. Recorded honestly, never silently
    dropped — a missed deadline is data the retrospective needs (P3)."""
    if deadline.status not in ("tracked", "alerted"):
        raise DeadlineValidationError(
            f"deadline {deadline.id} is {deadline.status}; only a tracked or "
            "alerted deadline can be missed"
        )
    return replace(deadline, status="missed")


def deadline_event_payload(deadline: Deadline) -> dict:
    """The self-sufficient deadline payload for deadline.* events (EB-003):
    the full field set, so a recovery-grade replay reconstructs the row
    exactly. One source both the event producer and the recovery applier
    agree on (mirrors task_event_payload).

    NOTE: no deadline.* event type is registered yet — EB-006 §6.1 makes the
    taxonomy closed and additions ADR-gated. This payload builder exists for
    the transition logic that owns the shape; wiring it to a published event
    waits on that ADR.
    """
    return {
        "id": deadline.id,
        "competition_id": deadline.competition_id,
        "project_id": deadline.project_id,
        "kind": deadline.kind,
        "title": deadline.title,
        "at": deadline.at,
        "lead_days": list(deadline.lead_days),
        "status": deadline.status,
        "created_at": deadline.created_at.isoformat(),
        "updated_at": deadline.updated_at.isoformat(),
        "device_id": deadline.device_id,
        "revision": deadline.revision,
    }
