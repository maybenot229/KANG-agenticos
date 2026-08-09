"""Goal domain service — invariants for the goal entity.

Layer: domain/projects (goals live alongside projects/milestones in this
package's cluster — see this package's own `__init__.py`, and `07_DATABASE`
§5.2's grouping of goal/project/milestone/competition as one shape family).
Capability service; deterministic, zero I/O.
Constitutional home: 07_DATABASE §5.2 (goal shape, horizon/status enums);
ADR-016 (goal.created, the entity's first write path — the standing
pattern ADR-013/014/015 established, generalized here).

`achieve_goal`/`revise_goal`/`retire_goal` (ADR-018, 2026-08-09) are the
entity's first status transitions, each `active -> <terminal>`, mirroring
`deadline_service.py`'s `mark_alerted`/`mark_met`/`mark_missed` exact shape.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from kang.domain.ports.clock import Clock
from kang.domain.ports.goal_store import GOAL_HORIZONS, GOAL_STATUSES, Goal

__all__ = [
    "GoalDraft",
    "GoalValidationError",
    "achieve_goal",
    "create_goal",
    "goal_event_payload",
    "retire_goal",
    "revise_goal",
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


def _transition(goal: Goal, target: str, clock: Clock) -> Goal:
    if goal.status != "active":
        raise GoalValidationError(f"goal {goal.id} is {goal.status}, not active")
    return replace(goal, status=target, updated_at=clock.now())


def achieve_goal(goal: Goal, clock: Clock) -> Goal:
    """`active -> achieved`: Kang made it."""
    return _transition(goal, "achieved", clock)


def revise_goal(goal: Goal, clock: Clock) -> Goal:
    """`active -> revised`: the goal's own scope/aim changed enough that
    the original statement no longer holds — recorded honestly rather
    than silently editing the row in place, same "never quietly rewrite
    intent" reasoning `deadline_service.mark_missed` states for its own
    entity."""
    return _transition(goal, "revised", clock)


def retire_goal(goal: Goal, clock: Clock) -> Goal:
    """`active -> retired`: no longer pursued, not because it was met or
    revised — distinct from both."""
    return _transition(goal, "retired", clock)


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
