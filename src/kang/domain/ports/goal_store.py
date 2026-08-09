"""Goal store port — persistence contract for the goal entity.

Layer: domain/ports. Ports own their datatypes (17 §7): the Goal shape
lives here so both sides of the firewall may import it; goal *invariants
and services* live in domain/goals.
Constitutional home: 07_DATABASE §5.2 (goal table), DB-002 (SQL confined
to the store layer behind this port), ADR-016 (goal.created — the
entity's first write path).

Tracking only (ADR-016, mirroring ADR-013's own scope statement for
project): this pass's port surface is create + list, nothing more. No
status-transition (`achieve`/`revise`/`retire`) or update/delete path
exists yet — added when a real operation needs one, not speculatively
widened now (PS-006).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

__all__ = [
    "GOAL_HORIZONS",
    "GOAL_STATUSES",
    "Goal",
    "GoalStore",
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


class GoalStore(Protocol):
    """Persistence port for goals. Implementations: SqliteGoalStore (real),
    FakeGoalStore (adapters/fakes — contract-tested against the real one,
    13 §2.3). Tracking-only surface: create + list; see module docstring
    for why get/update/delete aren't here yet."""

    def create(self, goal: Goal) -> None:
        """Persist a new goal. The change is capture-logged (07 §5.6,
        ADR-016's trigger)."""
        ...

    def list_all(self) -> list[Goal]:
        """Every goal, regardless of status or horizon — the tracking view
        has no natural single-axis filter the way deadlines do. Deterministic
        total order: (title, id) case-insensitively, so identical state
        always yields byte-identical output (13 §2.6), same discipline as
        `ProjectStore.list_all()`."""
        ...
