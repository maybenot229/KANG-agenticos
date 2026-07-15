"""Operation handlers — the thin glue from the contract to domain services.

Layer: api.
Constitutional home: 12_API §2 (handlers contain dispatch-to-domain only; an
`if` about domain semantics here is a defect), §7 (commands), §8 (queries),
§12 (explainability). Each handler is built with its domain dependencies
bound at the composition root; the dispatcher supplies (context, params).

task.create follows EB-004 through the bus: the task.created event is
published on the truth the task domain owns (principal `kernel:tasks`,
EB-010) with the request's correlation_id threaded through, and the state
commit is the bus's step 3.
"""

from __future__ import annotations

from typing import Any, Callable

from kang.api.dispatch import Handler, HandlerContext
from kang.api.errors import ApiError
from kang.api.registry import registry_snapshot
from kang.domain.ports.clock import Clock
from kang.domain.ports.eventlog import EventEnvelope
from kang.domain.ports.invocation import InvocationNotFound, InvocationStore
from kang.domain.ports.task_store import TaskNotFoundError, TaskStore
from kang.domain.tasks import (
    TaskDraft,
    TaskValidationError,
    create_task,
    task_event_payload,
)
from kang.kernel.audit.service import AuditService
from kang.kernel.bus.bus import EventBus

__all__ = [
    "make_explain_invocation_handler",
    "make_explain_stub_handler",
    "make_registry_get_handler",
    "make_task_create_handler",
    "make_task_get_handler",
]

TASKS_PRINCIPAL = "kernel:tasks"  # the domain that owns task truth (EB-010)


def make_registry_get_handler() -> Handler:
    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        return registry_snapshot()

    return handler


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


def make_explain_invocation_handler(
    invocations: InvocationStore, audit: AuditService
) -> Handler:
    """explain.invocation (12 §12): reconstruct from PERMANENT storage —
    the invocation row + the audit chain — by correlation_id. Never the
    event log (its 90-day retention would break the ≥180-day guarantee)."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        target = params.get("correlation_id")
        if not isinstance(target, str) or not target:
            raise ApiError(
                "invalid_request", "explain.invocation requires a 'correlation_id'"
            )
        try:
            invocation = invocations.by_correlation(target)
        except InvocationNotFound as exc:
            raise ApiError(
                "not_found", f"no invocation for correlation_id {target}"
            ) from exc
        chain = [
            {
                "action": record.entry.action,
                "principal": record.entry.principal,
                "at": record.entry.at,
                "details": record.entry.details,
            }
            for record in audit.records_for_correlation(target)
        ]
        return {
            "correlation_id": target,
            "trigger": invocation.trigger,
            "operation": invocation.operation,
            "principal": invocation.principal,
            "kind": invocation.kind,
            "manifest": invocation.manifest,  # None for non-agent operations
            "started": invocation.started,
            "finished": invocation.finished,
            "outcome": invocation.outcome,
            "chain": chain,
            "reconstructed_from": "invocation + audit (permanent storage)",
        }

    return handler


def make_explain_stub_handler(kind: str) -> Handler:
    """explain.plan_item/notification/suggestion/memory (12 §12): registered
    now; their subjects (plans, notifications, memory) arrive at M5/Phase 2.
    Until then they honestly return not_found — never a synthesized narrative
    (A4)."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        raise ApiError(
            "not_found",
            f"no {kind} to explain yet — its subject arrives in a later milestone",
        )

    return handler
