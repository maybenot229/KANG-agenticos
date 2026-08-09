"""FakeMilestoneStore — in-memory MilestoneStore, contract-paired
(13 §2.3).

Layer: adapters/fakes.
Constitutional home: 11_CODING §5/§7 (every port has an in-memory fake).
"""

from __future__ import annotations

from dataclasses import replace

from kang.domain.ports.clock import Clock
from kang.domain.ports.milestone_store import (
    Milestone,
    MilestoneNotFoundError,
    MilestoneRevisionConflictError,
)

__all__ = ["FakeMilestoneStore"]


class FakeMilestoneStore:
    """MilestoneStore over a dict. Mirrors the port contract exactly:
    optimistic revision checks, bump-on-update."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._milestones: dict[str, Milestone] = {}

    def create(self, milestone: Milestone) -> None:
        if milestone.id in self._milestones:
            raise ValueError(f"duplicate milestone {milestone.id}")
        self._milestones[milestone.id] = milestone

    def get(self, milestone_id: str) -> Milestone:
        try:
            return self._milestones[milestone_id]
        except KeyError:
            raise MilestoneNotFoundError(milestone_id) from None

    def update(self, milestone: Milestone) -> Milestone:
        current = self.get(milestone.id)
        if current.revision != milestone.revision:
            raise MilestoneRevisionConflictError(
                f"milestone {milestone.id}: expected revision "
                f"{milestone.revision}, store has {current.revision}"
            )
        committed = replace(
            milestone, updated_at=self._clock.now(), revision=milestone.revision + 1
        )
        self._milestones[milestone.id] = committed
        return committed

    def list_for_project(self, project_id: str) -> list[Milestone]:
        return sorted(
            (m for m in self._milestones.values() if m.project_id == project_id),
            key=lambda m: (m.due is None, m.due or "", m.id),
        )
