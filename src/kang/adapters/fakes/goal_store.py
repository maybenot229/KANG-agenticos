"""FakeGoalStore — in-memory GoalStore, contract-paired (13 §2.3).

Layer: adapters/fakes.
Constitutional home: 11_CODING §5/§7 (every port has an in-memory fake).
"""

from __future__ import annotations

from dataclasses import replace

from kang.domain.ports.clock import Clock
from kang.domain.ports.goal_store import (
    Goal,
    GoalNotFoundError,
    GoalRevisionConflictError,
)

__all__ = ["FakeGoalStore"]


class FakeGoalStore:
    """GoalStore over a dict. Mirrors the port contract exactly:
    optimistic revision checks, bump-on-update."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._goals: dict[str, Goal] = {}

    def create(self, goal: Goal) -> None:
        if goal.id in self._goals:
            raise ValueError(f"duplicate goal {goal.id}")
        self._goals[goal.id] = goal

    def get(self, goal_id: str) -> Goal:
        try:
            return self._goals[goal_id]
        except KeyError:
            raise GoalNotFoundError(goal_id) from None

    def update(self, goal: Goal) -> Goal:
        current = self.get(goal.id)
        if current.revision != goal.revision:
            raise GoalRevisionConflictError(
                f"goal {goal.id}: expected revision {goal.revision}, "
                f"store has {current.revision}"
            )
        committed = replace(
            goal, updated_at=self._clock.now(), revision=goal.revision + 1
        )
        self._goals[goal.id] = committed
        return committed

    def list_all(self) -> list[Goal]:
        return sorted(self._goals.values(), key=lambda g: (g.title.casefold(), g.id))
