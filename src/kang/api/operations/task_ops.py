"""task.create / task.get / task.complete handlers.

Layer: api.
Constitutional home: 12_API §2/§7/§8. `task.create` follows EB-004 through
the bus: the task.created event is published on the truth the task domain
owns (principal `kernel:tasks`, EB-010) with the request's correlation_id
threaded through, and the state commit is the bus's step 3. `task.complete`
(added 2026-08-09) follows the same shape publishing `task.updated`
instead — already-registered event, ADR-004.
"""

from __future__ import annotations

from typing import Any, Callable

from kang.api.dispatch import Handler, HandlerContext
from kang.api.errors import ApiError
from kang.domain.ports.clock import Clock
from kang.domain.ports.eventlog import EventEnvelope
from kang.domain.ports.task_store import (
    RevisionConflictError,
    TaskNotFoundError,
    TaskStore,
)
from kang.domain.tasks import (
    TaskDraft,
    TaskValidationError,
    complete_task,
    create_task,
    task_event_payload,
)
from kang.kernel.bus.bus import EventBus

__all__ = [
    "TASKS_PRINCIPAL",
    "make_task_complete_handler",
    "make_task_create_handler",
    "make_task_get_handler",
]

TASKS_PRINCIPAL = "kernel:tasks"  # the domain that owns task truth (EB-010)


def make_task_create_handler(
    bus: EventBus,
    task_store: TaskStore,
    clock: Clock,
    new_id: Callable[[], str],
    device_id: str,
) -> Handler:
    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        title = params.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ApiError("invalid_request", "task.create requires a 'title'")
        try:
            task = create_task(
                TaskDraft(title=title, priority=int(params.get("priority", 3))),
                task_id=new_id(),
                clock=clock,
                device_id=device_id,
            )
        except (TaskValidationError, ValueError) as exc:
            raise ApiError("invalid_request", str(exc)) from exc
        envelope = EventEnvelope(
            event_id=new_id(),
            type="task.created",
            occurred_at=task.created_at.isoformat(),
            principal=TASKS_PRINCIPAL,
            correlation_id=context.correlation_id,
            device_id=device_id,
            payload=task_event_payload(task),
            recovery_grade=True,
            entity_refs=({"kind": "task", "id": task.id},),
        )
        bus.publish(envelope, commit_state=lambda: task_store.create(task))
        return {"task_id": task.id, "revision": task.revision}

    return handler


def make_task_get_handler(task_store: TaskStore) -> Handler:
    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        task_id = params.get("id")
        if not isinstance(task_id, str):
            raise ApiError("invalid_request", "task.get requires an 'id'")
        try:
            task = task_store.get(task_id)
        except TaskNotFoundError as exc:
            raise ApiError("not_found", f"no task {task_id}") from exc
        return {
            "id": task.id,
            "title": task.title,
            "status": task.status,
            "priority": task.priority,
            "revision": task.revision,
        }

    return handler


def make_task_complete_handler(
    bus: EventBus,
    task_store: TaskStore,
    clock: Clock,
    new_id: Callable[[], str],
    device_id: str,
) -> Handler:
    """`task.complete`: the task entity's only status transition today.
    Fetches the task, transitions it via `complete_task` (open/scheduled/
    deferred -> done, `completed_at`/`updated_at` stamped), publishes
    `task.updated` (already registered, ADR-004) under `kernel:tasks`,
    and commits via `TaskStore.update`'s existing optimistic-concurrency
    contract — mirrors `_publish_deadline_alert`'s shape (`deadline.updated`
    via `mark_alerted`), the only other built task/deadline transition.

    A stale read (fetched here, changed elsewhere before this commits) is
    a genuine, if rare, race for a resident single-user Core — `conflict`
    exists precisely for it (API-006: "returns the current revision")."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        task_id = params.get("id")
        if not isinstance(task_id, str) or not task_id:
            raise ApiError("invalid_request", "task.complete requires an 'id'")
        try:
            task = task_store.get(task_id)
        except TaskNotFoundError as exc:
            raise ApiError("not_found", f"no task {task_id}") from exc
        try:
            completed = complete_task(task, clock)
        except TaskValidationError as exc:
            raise ApiError("invalid_request", str(exc)) from exc

        # `commit_state` is a plain callable (no return value threaded
        # through `bus.publish`); capture the store's committed snapshot
        # (revision bumped) via a one-element closure cell.
        committed_box: list = []

        def _commit() -> None:
            committed_box.append(task_store.update(completed))

        try:
            bus.publish(
                EventEnvelope(
                    event_id=new_id(),
                    type="task.updated",
                    occurred_at=completed.updated_at.isoformat(),
                    principal=TASKS_PRINCIPAL,
                    correlation_id=context.correlation_id,
                    device_id=device_id,
                    payload=task_event_payload(completed),
                    recovery_grade=True,
                    entity_refs=({"kind": "task", "id": completed.id},),
                ),
                commit_state=_commit,
            )
        except RevisionConflictError as exc:
            current = task_store.get(task_id)
            raise ApiError(
                "conflict",
                f"task {task_id} changed since it was read",
                details={"current_revision": current.revision},
            ) from exc

        committed = committed_box[0]
        return {
            "task_id": committed.id,
            "revision": committed.revision,
            "completed_at": committed.completed_at.isoformat(),
        }

    return handler
