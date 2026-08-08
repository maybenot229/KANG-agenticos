"""FakeMilestoneStore — in-memory MilestoneStore, contract-paired
(13 §2.3).

Layer: adapters/fakes.
Constitutional home: 11_CODING §5/§7 (every port has an in-memory fake).
"""

from __future__ import annotations

from kang.domain.ports.milestone_store import Milestone

__all__ = ["FakeMilestoneStore"]


class FakeMilestoneStore:
    """MilestoneStore over a dict."""

    def __init__(self) -> None:
        self._milestones: dict[str, Milestone] = {}

    def create(self, milestone: Milestone) -> None:
        if milestone.id in self._milestones:
            raise ValueError(f"duplicate milestone {milestone.id}")
        self._milestones[milestone.id] = milestone

    def list_for_project(self, project_id: str) -> list[Milestone]:
        return sorted(
            (m for m in self._milestones.values() if m.project_id == project_id),
            key=lambda m: (m.due is None, m.due or "", m.id),
        )
