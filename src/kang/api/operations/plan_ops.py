"""plan.generate handler — the deterministic morning plan (FR-001).

Layer: api.
Constitutional home: 12_API §2/§7, ADR-004 (plan.generated is derived
state, non-recovery-grade — its durable effect rides task.updated).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable

from kang.api.dispatch import Handler, HandlerContext
from kang.api.operations.task_ops import TASKS_PRINCIPAL
from kang.domain.planner import PlanInputs, build_plan, plan_generated_payload
from kang.domain.ports.calendar_store import CalendarStore
from kang.domain.ports.clock import Clock
from kang.domain.ports.deadline_store import DeadlineStore
from kang.domain.ports.eventlog import EventEnvelope
from kang.domain.ports.task_store import TaskStore
from kang.domain.tasks import task_event_payload
from kang.kernel.bus.bus import EventBus

__all__ = ["PLANNER_PRINCIPAL", "PlannerDeps", "make_plan_generate_handler"]

PLANNER_PRINCIPAL = "kernel:planner"  # announces plan.generated (EB-010)


@dataclass(frozen=True)
class PlannerDeps:
    """The Planner handler's collaborators (11 §4)."""

    bus: EventBus
    tasks: TaskStore
    deadlines: DeadlineStore
    calendar: CalendarStore
    clock: Clock
    new_id: Callable[[], str]
    device_id: str


def _stamp_quests(deps: PlannerDeps, plan, correlation_id: str) -> list[str]:
    """Commit the plan's durable half: `plan_date` on each quest.

    This is the mutation-first half of the same ordering discipline the
    deadline sweep uses. Each stamp is a task truth mutation, so it rides
    the recovery-grade `task.updated` (EB-003); `plan.generated` is
    published only after they all commit, because announcing a plan whose
    tasks are not yet stamped would advertise state that a crash could
    erase.
    """
    stamped: list[str] = []
    for quest in plan.quests:
        if quest.plan_date == plan.plan_date:
            continue  # idempotent: re-running a slot re-stamps nothing
        updated = replace(quest, plan_date=plan.plan_date)
        deps.bus.publish(
            EventEnvelope(
                event_id=deps.new_id(),
                type="task.updated",
                occurred_at=deps.clock.now().isoformat(),
                principal=TASKS_PRINCIPAL,
                correlation_id=correlation_id,
                device_id=deps.device_id,
                payload=task_event_payload(
                    replace(updated, revision=updated.revision + 1)
                ),
                recovery_grade=True,
                entity_refs=({"kind": "task", "id": quest.id},),
            ),
            commit_state=lambda t=updated: deps.tasks.update(t),
        )
        stamped.append(quest.id)
    return stamped


def make_plan_generate_handler(deps: PlannerDeps) -> Handler:
    """`plan.generate` — the deterministic morning plan (FR-001).

    Zero model calls, by construction: it reads P0 data and calls the pure
    `build_plan`. This is the release-blocking degradation floor (05 §16),
    built before any model exists to fall back from (18 §7.6).
    """

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        plan_date = params.get("plan_date") or deps.clock.now().date().isoformat()
        plan = build_plan(
            PlanInputs(
                plan_date=plan_date,
                tasks=tuple(deps.tasks.plannable()),
                deadlines=tuple(deps.deadlines.active()),
                calendar=tuple(deps.calendar.events_on(plan_date)),
            )
        )
        stamped = _stamp_quests(deps, plan, context.correlation_id)
        mutation_id = deps.new_id()
        deps.bus.publish(
            EventEnvelope(
                event_id=mutation_id,
                type="plan.generated",
                occurred_at=deps.clock.now().isoformat(),
                principal=PLANNER_PRINCIPAL,
                correlation_id=context.correlation_id,
                device_id=deps.device_id,
                payload=plan_generated_payload(plan),
                recovery_grade=False,  # derived state (ADR-004)
                entity_refs=tuple(
                    {"kind": "task", "id": quest.id} for quest in plan.quests
                ),
            ),
            # The quests' stamps already committed above; this announces the
            # plan, it does not carry it.
            commit_state=lambda: None,
        )
        return {
            "plan_date": plan.plan_date,
            "quest_ids": [t.id for t in plan.quests],
            "deadline_ids": [d.id for d in plan.deadlines],
            "calendar_event_ids": [e.provider_event_id for e in plan.calendar],
            "estimated_minutes": plan.estimated_minutes,
            "deferred_count": plan.deferred_count,
            "stamped": stamped,
        }

    return handler
