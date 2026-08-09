"""goal.create / goal.list handlers.

Layer: api.
Constitutional home: 12_API §2/§7/§8, ADR-016 (goal.created — the standing
pattern ADR-013/014/015 established, first applied to goal here).
"""

from __future__ import annotations

from typing import Any, Callable

from kang.api.dispatch import Handler, HandlerContext
from kang.api.errors import ApiError
from kang.domain.ports.clock import Clock
from kang.domain.ports.eventlog import EventEnvelope
from kang.domain.ports.goal_store import GoalStore
from kang.domain.projects.goal_service import (
    GoalDraft,
    GoalValidationError,
    create_goal,
    goal_event_payload,
)
from kang.kernel.bus.bus import EventBus

__all__ = [
    "GOALS_PRINCIPAL",
    "make_goal_create_handler",
    "make_goal_list_handler",
]

GOALS_PRINCIPAL = "kernel:goals"  # owns goal truth (EB-010, ADR-016)


def make_goal_create_handler(
    bus: EventBus,
    goal_store: GoalStore,
    clock: Clock,
    new_id: Callable[[], str],
    device_id: str,
) -> Handler:
    """`goal.create` (ADR-016): the goal entity's first write path —
    tracking only, mirrors `make_project_create_handler`'s exact shape.
    Publishes `goal.created` (recovery-grade, full row) under
    `kernel:goals` (EB-010: the domain service publishes, not the
    requester) — `commit_state` only runs inside `bus.publish` (EB-004),
    so this is the only way the write can commit at all."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        try:
            goal = create_goal(
                GoalDraft(
                    title=params.get("title", ""),
                    horizon=params.get("horizon", ""),
                    description=params.get("description"),
                    status=params.get("status", "active"),
                ),
                goal_id=new_id(),
                clock=clock,
                device_id=device_id,
            )
        except GoalValidationError as exc:
            raise ApiError("invalid_request", str(exc)) from exc
        bus.publish(
            EventEnvelope(
                event_id=new_id(),
                type="goal.created",
                occurred_at=goal.updated_at.isoformat(),
                principal=GOALS_PRINCIPAL,
                correlation_id=context.correlation_id,
                device_id=device_id,
                payload=goal_event_payload(goal),
                recovery_grade=True,
                entity_refs=({"kind": "goal", "id": goal.id},),
            ),
            commit_state=lambda: goal_store.create(goal),
        )
        return {"goal_id": goal.id, "revision": goal.revision}

    return handler


def make_goal_list_handler(goal_store: GoalStore) -> Handler:
    """`goal.list` (ADR-016, tracking only): every goal, title-then-id
    ordered — `GoalStore.list_all()`'s existing contract, exposed
    verbatim. No new domain logic."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "goals": [
                {
                    "id": g.id,
                    "title": g.title,
                    "horizon": g.horizon,
                    "status": g.status,
                    "description": g.description,
                }
                for g in goal_store.list_all()
            ]
        }

    return handler
