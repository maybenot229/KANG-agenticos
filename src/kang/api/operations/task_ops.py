"""task.create / task.get handlers.

Layer: api.
Constitutional home: 12_API §2/§7/§8. `task.create` follows EB-004 through
the bus: the task.created event is published on the truth the task domain
owns (principal `kernel:tasks`, EB-010) with the request's correlation_id
threaded through, and the state commit is the bus's step 3.
"""

from __future__ import annotations

from typing import Any, Callable

from kang.api.dispatch import Handler, HandlerContext
from kang.api.errors import ApiError
from kang.domain.ports.clock import Clock
from kang.domain.ports.eventlog import EventEnvelope
from kang.domain.ports.task_store import TaskNotFoundError, TaskStore
from kang.domain.tasks import (
    TaskDraft,
    TaskValidationError,
    create_task,
    task_event_payload,
)
from kang.kernel.bus.bus import EventBus

__all__ = ["TASKS_PRINCIPAL", "make_task_create_handler", "make_task_get_handler"]

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
