"""Deadline store port — persistence contract for the deadline entity.

Layer: domain/ports. Ports own their datatypes (17 §7): the Deadline shape
lives here so both sides of the firewall may import it; deadline *invariants
and services* live in domain/deadlines.
Constitutional home: 07_DATABASE §5.2 (deadline table: kinds, statuses,
lead_days JSON alert schedule), DB-002 (SQL confined to the store layer
behind this port), DB-001/DB-003 (optimistic revision discipline surfaces as
RevisionConflictError), 05_AGENTS Appendix A (deadline_sweep reads
`v_active_deadlines` and marks alerted — `deadlines.mark_alerted`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

__all__ = [
    "DEADLINE_KINDS",
    "DEADLINE_STATUSES",
    "DEFAULT_LEAD_DAYS",
    "Deadline",
    "DeadlineNotFoundError",
    "DeadlineStore",
    "DeadlineStoreError",
    "DeadlineRevisionConflictError",
]

DEADLINE_KINDS = ("registration", "submission", "event", "school", "custom")
DEADLINE_STATUSES = ("tracked", "alerted", "met", "missed", "cancelled")

# 07 §5.2's `lead_days DEFAULT '[14,7,3,1]'` — the alert schedule in days
# before `at`. Descending: the sweep fires the largest threshold first.
DEFAULT_LEAD_DAYS: tuple[int, ...] = (14, 7, 3, 1)


@dataclass(frozen=True)
class Deadline:
    """One deadline row (07 §5.2), sync quartet included (D009).

    Immutable snapshot: mutation happens by command through the store, which
    returns the new snapshot with its committed revision.

    `at` is an ISO-8601 string, not a datetime, mirroring the column: a
    deadline is a stated calendar instant, and re-parsing it through a
    timezone-aware type on every read would invite the drift 07 §4 warns
    about. The domain service parses it explicitly when it needs arithmetic.
    """

    id: str
    kind: str
    title: str
    at: str
    status: str
    created_at: datetime
    updated_at: datetime
    device_id: str
    revision: int
    competition_id: str | None = None
    project_id: str | None = None
    lead_days: tuple[int, ...] = DEFAULT_LEAD_DAYS


class DeadlineStoreError(Exception):
    """Base of the deadline-store failure hierarchy (11 §9: typed errors)."""


class DeadlineNotFoundError(DeadlineStoreError):
    """No deadline with the given id exists."""


class DeadlineRevisionConflictError(DeadlineStoreError):
    """Optimistic concurrency check failed: expected revision is stale."""


class DeadlineStore(Protocol):
    """Persistence port for deadlines. Implementations: SqliteDeadlineStore
    (real), FakeDeadlineStore (adapters/fakes — contract-tested against the
    real one, 13 §2.3)."""

    def create(self, deadline: Deadline) -> None:
        """Persist a new deadline. The change is capture-logged (07 §5.6)."""
        ...

    def get(self, deadline_id: str) -> Deadline:
        """Return the deadline or raise DeadlineNotFoundError."""
        ...

    def update(self, deadline: Deadline) -> Deadline:
        """Persist changed fields; ``deadline.revision`` is the expected
        current revision. Returns the committed snapshot (revision bumped,
        updated_at stamped). Raises DeadlineRevisionConflictError on
        staleness."""
        ...

    def active(self) -> list[Deadline]:
        """Every `tracked` deadline, soonest first — the `v_active_deadlines`
        read shape (07 §4.1) the Planner and deadline_sweep consume.
        Deterministic total order: (at, id), so identical state always
        yields byte-identical plan input (13 §2.6)."""
        ...

    def delete(self, deadline_id: str, deleted_by: str) -> None:
        """Destroy the row, leaving a tombstone (07 §5.1) and a capture row."""
        ...
