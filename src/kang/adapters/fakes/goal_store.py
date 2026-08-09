"""FakeGoalStore — in-memory GoalStore, contract-paired (13 §2.3).

Layer: adapters/fakes.
Constitutional home: 11_CODING §5/§7 (every port has an in-memory fake).
"""

from __future__ import annotations

from kang.domain.ports.goal_store import Goal

__all__ = ["FakeGoalStore"]


class FakeGoalStore:
    """GoalStore over a dict."""

    def __init__(self) -> None:
        self._goals: dict[str, Goal] = {}

    def create(self, goal: Goal) -> None:
        if goal.id in self._goals:
            raise ValueError(f"duplicate goal {goal.id}")
        self._goals[goal.id] = goal

    def list_all(self) -> list[Goal]:
        return sorted(self._goals.values(), key=lambda g: (g.title.casefold(), g.id))
