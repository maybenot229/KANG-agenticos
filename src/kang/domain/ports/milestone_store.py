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

`reach`/`miss`/`drop` (ADR-018, 2026-08-09) are the entity's first status
transitions: `get`/`update` join `create`/`list_for_project`, mirroring
`TaskStore`'s exact optimistic-concurrency contract (`WHERE id = ? AND
revision = ?`, `NotFoundError`/`RevisionConflictError`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

__all__ = [
    "MILESTONE_STATUSES",
    "Milestone",
    "MilestoneNotFoundError",
    "MilestoneRevisionConflictError",
    "MilestoneStore",
    "MilestoneStoreError",
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


class MilestoneStoreError(Exception):
    """Base of the milestone-store failure hierarchy (11 §9: typed
    errors)."""


class MilestoneNotFoundError(MilestoneStoreError):
    """No milestone with the given id exists."""


class MilestoneRevisionConflictError(MilestoneStoreError):
    """Optimistic concurrency check failed: expected revision is stale."""


class MilestoneStore(Protocol):
    """Persistence port for milestones. Implementations:
    SqliteMilestoneStore (real), FakeMilestoneStore (adapters/fakes —
    contract-tested against the real one, 13 §2.3). `get`/`update`
    (ADR-018) join the tracking-only `create`/`list_for_project`; delete
    still has no caller (07_DATABASE Appendix B's CASCADE handles the
    only removal path that exists, project deletion)."""

    def create(self, milestone: Milestone) -> None:
        """Persist a new milestone. The change is capture-logged (07 §5.6,
        ADR-015's trigger)."""
        ...

    def get(self, milestone_id: str) -> Milestone:
        """Return the milestone or raise MilestoneNotFoundError."""
        ...

    def update(self, milestone: Milestone) -> Milestone:
        """Persist a status transition; `milestone.revision` is the
        expected current revision. Returns the committed snapshot
        (revision bumped, `updated_at` stamped). Raises
        MilestoneRevisionConflictError on staleness,
        MilestoneNotFoundError if the id no longer exists."""
        ...

    def list_for_project(self, project_id: str) -> list[Milestone]:
        """Every milestone belonging to one project, regardless of status
        — same "no natural horizon to filter by" reasoning as
        `ProjectStore.list_all()`. Deterministic total order: (due IS
        NULL, due, id) so dated milestones sort by date and undated ones
        land last, stable (13 §2.6)."""
        ...
