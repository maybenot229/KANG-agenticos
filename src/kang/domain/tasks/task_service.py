"""Task domain service — invariants and transitions for the task entity.

Layer: domain/tasks (capability service; deterministic, zero I/O).
Constitutional home: 02_PRD tasks capability; 07_DATABASE §5.2 (statuses,
priority bounds); 17 §6.1 (algorithms live in domain services, never agents).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from kang.domain.ports.clock import Clock
from kang.domain.ports.task_store import TASK_STATUSES, Task

__all__ = [
    "TaskDraft",
    "TaskValidationError",
    "complete_task",
    "create_task",
    "task_event_payload",
]


class TaskValidationError(Exception):
    """A task invariant was violated. Raised before anything is persisted."""


@dataclass(frozen=True)
class TaskDraft:
    """What Kang states about a new task; the system stamps the rest
    (11 §4: beyond four parameters, it's a dataclass)."""

    title: str
    status: str = "open"
    priority: int = 3
    project_id: str | None = None
    notes: str | None = None
    due: str | None = None


def _validate(draft: TaskDraft) -> None:
    if not draft.title.strip():
        raise TaskValidationError("title must be non-empty")
    if draft.status not in TASK_STATUSES:
        raise TaskValidationError(f"status must be one of {TASK_STATUSES}")
    if not 1 <= draft.priority <= 5:
        raise TaskValidationError("priority must be between 1 and 5")


def create_task(draft: TaskDraft, task_id: str, clock: Clock, device_id: str) -> Task:
    """Build a valid new Task with the sync quartet stamped (D009):
    created_at/updated_at from the injected clock, device_id, revision 1."""
    _validate(draft)
    now = clock.now()
    return Task(
        id=task_id,
        title=draft.title,
        status=draft.status,
        priority=draft.priority,
        project_id=draft.project_id,
        notes=draft.notes,
        due=draft.due,
        created_at=now,
        updated_at=now,
        device_id=device_id,
        revision=1,
    )


def complete_task(task: Task, clock: Clock) -> Task:
    """Return the completed snapshot; persistence bumps the revision."""
    if task.status == "done":
        raise TaskValidationError(f"task {task.id} is already done")
    return replace(task, status="done", completed_at=clock.now())


def task_event_payload(task: Task) -> dict:
    """The self-sufficient task payload for task.* events (EB-003): the full
    field set, so a recovery-grade replay reconstructs the row exactly. One
    source both the event producer (api) and the recovery applier agree on."""
    return {
        "id": task.id,
        "project_id": task.project_id,
        "title": task.title,
        "notes": task.notes,
        "status": task.status,
        "priority": task.priority,
        "due": task.due,
        "plan_date": task.plan_date,
        "estimate_min": task.estimate_min,
        "actual_min": task.actual_min,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "device_id": task.device_id,
        "revision": task.revision,
    }
