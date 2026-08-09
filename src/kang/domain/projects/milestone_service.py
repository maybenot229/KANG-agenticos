"""Milestone domain service — invariants for the milestone entity.

Layer: domain/projects (milestones are a project sub-resource, not their
own top-level domain — see the port's own docstring). Capability service;
deterministic, zero I/O.
Constitutional home: 07_DATABASE §5.2 (milestone shape, status enum);
ADR-015 (milestone.created, the entity's first write path).

`mark_reached`/`mark_missed`/`mark_dropped` (ADR-018, 2026-08-09) are the
entity's first status transitions, each `pending -> <terminal>`, mirroring
`deadline_service.py`'s `mark_alerted`/`mark_met`/`mark_missed` exact shape.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from kang.domain.ports.clock import Clock
from kang.domain.ports.milestone_store import MILESTONE_STATUSES, Milestone

__all__ = [
    "MilestoneDraft",
    "MilestoneValidationError",
    "create_milestone",
    "mark_dropped",
    "mark_missed",
    "mark_reached",
    "milestone_event_payload",
]


class MilestoneValidationError(Exception):
    """A milestone invariant was violated. Raised before anything is
    persisted."""


@dataclass(frozen=True)
class MilestoneDraft:
    """What Kang states about a new milestone on a project he already
    tracks; the system stamps the rest (11 §4: beyond four parameters,
    it's a dataclass)."""

    project_id: str
    title: str
    due: str | None = None
    status: str = "pending"


def _validate(draft: MilestoneDraft) -> None:
    if not draft.project_id.strip():
        raise MilestoneValidationError("project_id must be non-empty")
    if not draft.title.strip():
        raise MilestoneValidationError("title must be non-empty")
    if draft.status not in MILESTONE_STATUSES:
        raise MilestoneValidationError(f"status must be one of {MILESTONE_STATUSES}")
    if draft.due is not None:
        # Mirrors deadline_service.py::_parse_at exactly (same stdlib call,
        # same failure condition — not a stricter check).
        try:
            datetime.fromisoformat(draft.due)
        except ValueError as exc:
            raise MilestoneValidationError(
                f"milestone `due` must be ISO-8601, got {draft.due!r}"
            ) from exc


def create_milestone(
    draft: MilestoneDraft, milestone_id: str, clock: Clock, device_id: str
) -> Milestone:
    """Build a valid new Milestone with the sync quartet stamped (D009):
    created_at/updated_at from the injected clock, device_id, revision 1.
    Does NOT verify `project_id` references a real project — that is the
    database's own FK constraint's job (07 §5.2's `REFERENCES project(id)`),
    not duplicated here (11 §9: one invariant, one owner)."""
    _validate(draft)
    now = clock.now()
    return Milestone(
        id=milestone_id,
        project_id=draft.project_id,
        title=draft.title,
        due=draft.due,
        status=draft.status,
        created_at=now,
        updated_at=now,
        device_id=device_id,
        revision=1,
    )


def _transition(milestone: Milestone, target: str, clock: Clock) -> Milestone:
    if milestone.status != "pending":
        raise MilestoneValidationError(
            f"milestone {milestone.id} is {milestone.status}, not pending"
        )
    return replace(milestone, status=target, updated_at=clock.now())


def mark_reached(milestone: Milestone, clock: Clock) -> Milestone:
    """`pending -> reached`: Kang hit it."""
    return _transition(milestone, "reached", clock)


def mark_missed(milestone: Milestone, clock: Clock) -> Milestone:
    """`pending -> missed`. Recorded honestly, never silently dropped —
    same reasoning as `deadline_service.mark_missed`."""
    return _transition(milestone, "missed", clock)


def mark_dropped(milestone: Milestone, clock: Clock) -> Milestone:
    """`pending -> dropped`: the milestone itself is no longer relevant
    (the project's plan changed), distinct from `missed` (it was relevant
    and the date passed)."""
    return _transition(milestone, "dropped", clock)


def milestone_event_payload(milestone: Milestone) -> dict:
    """The self-sufficient milestone payload for `milestone.created`
    (EB-003, ADR-015): the full field set, so a recovery-grade replay
    reconstructs the row exactly. Mirrors `project_event_payload`."""
    return {
        "id": milestone.id,
        "project_id": milestone.project_id,
        "title": milestone.title,
        "due": milestone.due,
        "status": milestone.status,
        "created_at": milestone.created_at.isoformat(),
        "updated_at": milestone.updated_at.isoformat(),
        "device_id": milestone.device_id,
        "revision": milestone.revision,
    }
