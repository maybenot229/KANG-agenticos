"""Task store port — persistence contract for the task entity.

Layer: domain/ports. Ports own their datatypes (17 §7): the Task shape lives
here so both sides of the firewall may import it; task *invariants and
services* live in domain/tasks.
Constitutional home: 07_DATABASE §5.2 (task table), DB-002 (SQL confined to
the store layer behind this port), DB-001/DB-003 (optimistic revision
discipline surfaces as RevisionConflictError).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

__all__ = [
    "Task",
    "TaskNotFoundError",
    "TaskStore",
    "TaskStoreError",
    "RevisionConflictError",
]

TASK_STATUSES = ("open", "scheduled", "done", "deferred", "dropped")


@dataclass(frozen=True)
class Task:
    """One task row (07 §5.2), sync quartet included (D009).

    Immutable snapshot: mutation happens by command through the store, which
    returns the new snapshot with its committed revision.
    """

    id: str
    title: str
    status: str
    priority: int
    created_at: datetime
    updated_at: datetime
    device_id: str
    revision: int
    project_id: str | None = None
    notes: str | None = None
    due: str | None = None
    plan_date: str | None = None
    estimate_min: int | None = None
    actual_min: int | None = None
    completed_at: datetime | None = None


class TaskStoreError(Exception):
    """Base of the task-store failure hierarchy (11 §9: typed errors)."""


class TaskNotFoundError(TaskStoreError):
    """No task with the given id exists."""


class RevisionConflictError(TaskStoreError):
    """Optimistic concurrency check failed: expected revision is stale."""


class TaskStore(Protocol):
    """Persistence port for tasks. Implementations: SqliteTaskStore (real),
    FakeTaskStore (adapters/fakes — contract-tested against the real one,
    13 §2.3)."""

    def create(self, task: Task) -> None:
        """Persist a new task. The change is capture-logged (07 §5.6)."""
        ...

    def get(self, task_id: str) -> Task:
        """Return the task or raise TaskNotFoundError."""
        ...

    def update(self, task: Task) -> Task:
        """Persist changed fields; ``task.revision`` is the expected current
        revision. Returns the committed snapshot (revision bumped,
        updated_at stamped). Raises RevisionConflictError on staleness."""
        ...

    def delete(self, task_id: str, deleted_by: str) -> None:
        """Destroy the row, leaving a tombstone (07 §5.1) and a capture row."""
        ...
