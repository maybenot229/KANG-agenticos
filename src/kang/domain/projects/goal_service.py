"""Goal domain service — invariants for the goal entity.

Layer: domain/projects (goals live alongside projects/milestones in this
package's cluster — see this package's own `__init__.py`, and `07_DATABASE`
§5.2's grouping of goal/project/milestone/competition as one shape family).
Capability service; deterministic, zero I/O.
Constitutional home: 07_DATABASE §5.2 (goal shape, horizon/status enums);
ADR-016 (goal.created, the entity's first write path — the standing
pattern ADR-013/014/015 established, generalized here).

Tracking only this pass: `create_goal` is the entity's whole surface — no
status-transition function exists yet (mirrors project_service.py's own
precedent exactly).
"""

from __future__ import annotations

from dataclasses import dataclass

from kang.domain.ports.clock import Clock
from kang.domain.ports.goal_store import GOAL_HORIZONS, GOAL_STATUSES, Goal

__all__ = [
    "GoalDraft",
    "GoalValidationError",
    "create_goal",
    "goal_event_payload",
]


class GoalValidationError(Exception):
    """A goal invariant was violated. Raised before anything is
    persisted."""


@dataclass(frozen=True)
class GoalDraft:
    """What Kang states about a new goal; the system stamps the rest
    (11 §4: beyond four parameters, it's a dataclass)."""

    title: str
    horizon: str
    description: str | None = None
    status: str = "active"


def _validate(draft: GoalDraft) -> None:
    if not draft.title.strip():
        raise GoalValidationError("title must be non-empty")
    if draft.horizon not in GOAL_HORIZONS:
        raise GoalValidationError(f"horizon must be one of {GOAL_HORIZONS}")
    if draft.status not in GOAL_STATUSES:
        raise GoalValidationError(f"status must be one of {GOAL_STATUSES}")


def create_goal(draft: GoalDraft, goal_id: str, clock: Clock, device_id: str) -> Goal:
    """Build a valid new Goal with the sync quartet stamped (D009):
    created_at/updated_at from the injected clock, device_id, revision 1."""
    _validate(draft)
    now = clock.now()
    return Goal(
        id=goal_id,
        title=draft.title,
        horizon=draft.horizon,
        status=draft.status,
        description=draft.description,
        created_at=now,
        updated_at=now,
        device_id=device_id,
        revision=1,
    )


def goal_event_payload(goal: Goal) -> dict:
    """The self-sufficient goal payload for `goal.created` (EB-003,
    ADR-016): the full field set, so a recovery-grade replay reconstructs
    the row exactly. Mirrors `project_event_payload`/`milestone_event_payload`."""
    return {
        "id": goal.id,
        "title": goal.title,
        "description": goal.description,
        "horizon": goal.horizon,
        "status": goal.status,
        "created_at": goal.created_at.isoformat(),
        "updated_at": goal.updated_at.isoformat(),
        "device_id": goal.device_id,
        "revision": goal.revision,
    }
