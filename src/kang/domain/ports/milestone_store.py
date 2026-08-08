"""Milestone store port — persistence contract for the milestone entity.

Layer: domain/ports. Ports own their datatypes (17 §7): the Milestone
shape lives here so both sides of the firewall may import it; milestone
*invariants and services* live in domain/projects (milestones are a
project sub-resource, not their own top-level domain — 07 §5.2's own
grouping, ADR-015's Context).
Constitutional home: 07_DATABASE §5.2 (milestone table), DB-002 (SQL
confined to the store layer behind this port), ADR-015 (milestone.created
— the entity's first write path), 07_DATABASE Appendix B (`project ->
milestone` is a pre-sanctioned CASCADE — a deleted project takes its
milestones with it; this port owns no delete of its own since nothing
calls one yet).

Tracking only: create + list-by-project, nothing more. No status-
transition (`reach`/`miss`/`drop`) exists yet — see ADR-015.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

__all__ = [
    "MILESTONE_STATUSES",
    "Milestone",
    "MilestoneStore",
]

MILESTONE_STATUSES = ("pending", "reached", "missed", "dropped")


@dataclass(frozen=True)
class Milestone:
    """One milestone row (07 §5.2), sync quartet included (D009).
    Immutable snapshot, matching Project's own shape/reasoning
    (`project_store.py`)."""

    id: str
    project_id: str
    title: str
    status: str
    created_at: datetime
    updated_at: datetime
    device_id: str
    revision: int
    due: str | None = None


class MilestoneStore(Protocol):
    """Persistence port for milestones. Implementations:
    SqliteMilestoneStore (real), FakeMilestoneStore (adapters/fakes —
    contract-tested against the real one, 13 §2.3). Tracking-only surface:
    create + list-for-project; see module docstring for why get/update/
    delete aren't here yet."""

    def create(self, milestone: Milestone) -> None:
        """Persist a new milestone. The change is capture-logged (07 §5.6,
        ADR-015's trigger)."""
        ...

    def list_for_project(self, project_id: str) -> list[Milestone]:
        """Every milestone belonging to one project, regardless of status
        — same "no natural horizon to filter by" reasoning as
        `ProjectStore.list_all()`. Deterministic total order: (due IS
        NULL, due, id) so dated milestones sort by date and undated ones
        land last, stable (13 §2.6)."""
        ...
