"""Goal store port — persistence contract for the goal entity.

Layer: domain/ports. Ports own their datatypes (17 §7): the Goal shape
lives here so both sides of the firewall may import it; goal *invariants
and services* live in domain/goals.
Constitutional home: 07_DATABASE §5.2 (goal table), DB-002 (SQL confined
to the store layer behind this port), ADR-016 (goal.created — the
entity's first write path).

`achieve`/`revise`/`retire` (ADR-018, 2026-08-09) are the entity's first
status transitions: `get`/`update` join `create`/`list_all`, mirroring
`TaskStore`'s exact optimistic-concurrency contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

__all__ = [
    "GOAL_HORIZONS",
    "GOAL_STATUSES",
    "Goal",
    "GoalNotFoundError",
    "GoalRevisionConflictError",
    "GoalStore",
    "GoalStoreError",
]

GOAL_HORIZONS = ("quarter", "year", "life")
GOAL_STATUSES = ("active", "achieved", "revised", "retired")


@dataclass(frozen=True)
class Goal:
    """One goal row (07 §5.2), sync quartet included (D009). Immutable
    snapshot, matching Project's own shape/reasoning (`project_store.py`)."""

    id: str
    title: str
    horizon: str
    status: str
    created_at: datetime
    updated_at: datetime
    device_id: str
    revision: int
    description: str | None = None


class GoalStoreError(Exception):
    """Base of the goal-store failure hierarchy (11 §9: typed errors)."""


class GoalNotFoundError(GoalStoreError):
    """No goal with the given id exists."""


class GoalRevisionConflictError(GoalStoreError):
    """Optimistic concurrency check failed: expected revision is stale."""


class GoalStore(Protocol):
    """Persistence port for goals. Implementations: SqliteGoalStore (real),
    FakeGoalStore (adapters/fakes — contract-tested against the real one,
    13 §2.3). `get`/`update` (ADR-018) join `create`/`list_all`; delete
    still has no caller."""

    def create(self, goal: Goal) -> None:
        """Persist a new goal. The change is capture-logged (07 §5.6,
        ADR-016's trigger)."""
        ...

    def get(self, goal_id: str) -> Goal:
        """Return the goal or raise GoalNotFoundError."""
        ...

    def update(self, goal: Goal) -> Goal:
        """Persist a status transition; `goal.revision` is the expected
        current revision. Returns the committed snapshot (revision
        bumped, `updated_at` stamped). Raises GoalRevisionConflictError
        on staleness, GoalNotFoundError if the id no longer exists."""
        ...

    def list_all(self) -> list[Goal]:
        """Every goal, regardless of status or horizon — the tracking view
        has no natural single-axis filter the way deadlines do. Deterministic
        total order: (title, id) case-insensitively, so identical state
        always yields byte-identical output (13 §2.6), same discipline as
        `ProjectStore.list_all()`."""
        ...
