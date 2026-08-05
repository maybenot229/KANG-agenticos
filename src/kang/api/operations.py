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

from dataclasses import dataclass, replace
from typing import Any, Callable

from kang.api.dispatch import Handler, HandlerContext
from kang.api.errors import ApiError
from kang.api.registry import registry_snapshot
from kang.api.schemas.invocation import DEFAULT_LIMIT, MAX_LIMIT
from kang.domain.deadlines import (
    DeadlineDraft,
    DeadlineValidationError,
    create_deadline,
    deadline_event_payload,
    due_lead_thresholds,
    mark_alerted,
)
from kang.domain.planner import (
    PlanInputs,
    build_plan,
    plan_generated_payload,
)
from kang.domain.ports.calendar_store import CalendarStore
from kang.domain.ports.clock import Clock
from kang.domain.ports.deadline_store import Deadline, DeadlineStore
from kang.domain.ports.eventlog import EventEnvelope
from kang.domain.ports.held_action import (
    HeldActionExpired,
    HeldActionNotFound,
    HeldActionStore,
)
from kang.domain.ports.invocation import InvocationNotFound, InvocationStore
from kang.domain.ports.notification_store import (
    NotificationNotFoundError,
    NotificationStore,
)
from kang.domain.ports.scheduler import JobStore, KillSwitch
from kang.domain.ports.task_store import TaskNotFoundError, TaskStore
from kang.domain.tasks import (
    TaskDraft,
    TaskValidationError,
    create_task,
    task_event_payload,
)
from kang.kernel.audit.service import AuditService
from kang.kernel.bus.bus import EventBus
from kang.kernel.permissions.engine import PermissionEngine

__all__ = [
    "make_audit_list_handler",
    "make_deadline_create_handler",
    "make_deadline_list_handler",
    "make_deadline_sweep_handler",
    "make_explain_invocation_handler",
    "make_explain_stub_handler",
    "make_held_action_approve_handler",
    "make_held_action_cancel_handler",
    "make_held_action_list_handler",
    "make_invocation_list_handler",
    "make_notification_ack_handler",
    "make_permission_list_handler",
    "make_plan_generate_handler",
    "PlannerDeps",
    "make_registry_get_handler",
    "make_system_health_handler",
    "make_task_create_handler",
    "make_task_get_handler",
]

# 08_PLUGIN Appendix B style: one honest sentence per scope family,
# describing what holding it lets a principal do — not the plugin-install
# screen's per-plugin instance (this is the System-domain permission
# screen, 09_UI §7), but the same "plain-language consequence" contract.
# Keyed by family only (Scope.family, ignoring the qualifier) since every
# grant in `config/defaults/permissions.toml` today is either the bare `*`
# wildcard or a single-qualifier family — a scope whose family isn't
# listed here falls back to an honest "no description written yet" rather
# than a fabricated one (09_UI §4's "never pad" rule, applied to this
# screen too).
_SCOPE_CONSEQUENCES: dict[str, str] = {
    "*": (
        "Full authority over everything KANG can do — reserved for "
        "Kang's own first-party session."
    ),
    "events.publish": (
        "Can publish facts to the event bus under the named namespace — "
        "the kernel's own truth-recording mechanism, not visible data "
        "access."
    ),
    "tasks.write": (
        "Can create or modify tasks and stamp plan dates, within "
        "whatever operations it triggers allow."
    ),
    "task.write": "Can create tasks.",
    "task.read": "Can read tasks by id.",
    "deadlines.set": "Can create tracked deadlines.",
    "deadlines.read": "Can read the list of currently tracked deadlines.",
    "deadlines.mark_alerted": (
        "Can flip a deadline from tracked to alerted — the lead-time sweep's one write."
    ),
}


def _scope_consequence(scope: str) -> str:
    if scope == "*":
        return _SCOPE_CONSEQUENCES["*"]
    family = scope.split(":", 1)[0]
    return _SCOPE_CONSEQUENCES.get(
        family, f"No plain-language description written yet for {family!r}."
    )


TASKS_PRINCIPAL = "kernel:tasks"  # the domain that owns task truth (EB-010)
DEADLINES_PRINCIPAL = "kernel:deadlines"  # owns deadline truth (EB-010)
PLANNER_PRINCIPAL = "kernel:planner"  # announces plan.generated (EB-010)


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


def make_deadline_list_handler(deadline_store: DeadlineStore) -> Handler:
    """`deadline.list` (added 2026-08-05, dashboard Zone 2, 09_UI §4): every
    `tracked` deadline, soonest first — `DeadlineStore.active()`'s existing
    contract, already relied on by `deadline_sweep` and `plan.generate`
    below. No new domain logic; this handler is pure API-layer exposure,
    following `task.get`'s hand-picked-field convention rather than the
    full `deadline_event_payload` shape (that shape is for event replay)."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "deadlines": [
                {
                    "id": d.id,
                    "title": d.title,
                    "at": d.at,
                    "kind": d.kind,
                    "status": d.status,
                    "competition_id": d.competition_id,
                    "project_id": d.project_id,
                }
                for d in deadline_store.active()
            ]
        }

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


@dataclass(frozen=True)
class _AlertIds:
    """The ids and stamps one alert's two envelopes share (11 §4: beyond a
    few parameters, a dataclass). Generated by the caller so the sweep stays
    the only place the id source is read."""

    mutation_id: str
    fact_id: str
    occurred_at: str
    device_id: str


def _deadline_envelope(
    deadline, *, event_id: str, event_type: str, correlation_id: str, device_id: str
) -> EventEnvelope:
    """One deadline truth-mutation envelope. Recovery-grade with the full
    row (ADR-004): a lost write must replay exactly."""
    return EventEnvelope(
        event_id=event_id,
        type=event_type,
        occurred_at=deadline.updated_at.isoformat(),
        principal=DEADLINES_PRINCIPAL,
        correlation_id=correlation_id,
        device_id=device_id,
        payload=deadline_event_payload(deadline),
        recovery_grade=True,
        entity_refs=({"kind": "deadline", "id": deadline.id},),
    )


def make_deadline_create_handler(
    bus: EventBus,
    deadline_store: DeadlineStore,
    clock: Clock,
    new_id: Callable[[], str],
    device_id: str,
) -> Handler:
    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        try:
            deadline = create_deadline(
                DeadlineDraft(
                    title=params.get("title", ""),
                    at=params.get("at", ""),
                    kind=params.get("kind", "custom"),
                    competition_id=params.get("competition_id"),
                    project_id=params.get("project_id"),
                ),
                deadline_id=new_id(),
                clock=clock,
                device_id=device_id,
            )
        except DeadlineValidationError as exc:
            raise ApiError("invalid_request", str(exc)) from exc
        bus.publish(
            _deadline_envelope(
                deadline,
                event_id=new_id(),
                event_type="deadline.created",
                correlation_id=context.correlation_id,
                device_id=device_id,
            ),
            commit_state=lambda: deadline_store.create(deadline),
        )
        return {"deadline_id": deadline.id, "revision": deadline.revision}

    return handler


# ORDERING RULING — ADR-004 left this open to be decided against real code;
# decided here. One `tracked → alerted` flip publishes **two** events, in a
# fixed order:
#
#   1. `deadline.updated`     — carries the state commit. Recovery-grade,
#      full row. It is the redo record: EB-003 REQUIRES recovery-grade for
#      deadline truth mutations, and `alerted` is truth.
#   2. `deadline.approaching` — the trigger fact, `causation_id` set to
#      (1)'s event_id, committing no state of its own.
#
# Why not one event. Collapsing into `deadline.approaching` alone leaves the
# mutation with no recovery-grade redo record (EB-003 violation), and that
# type cannot itself be recovery-grade because EB-008 rule 2 states it
# "changes no row". Collapsing into `deadline.updated` alone forces the
# notifier to subscribe to a generic update and re-derive "is this
# approaching?" from status — domain semantics leaking into a subscriber,
# and contradicting 05 Appendix F, which names `deadline.approaching` as the
# notifier's and planner's trigger.
#
# Why this order. The commit must be durable before the fact is announced.
# Announcing first means a crash in between leaves a notification for a
# deadline still marked `tracked`, which the next sweep re-alerts — the
# duplicate 09_UI §9's 24h re-notification rule forbids.
def _publish_deadline_alert(
    bus: EventBus,
    store: DeadlineStore,
    alerted: Deadline,
    context: HandlerContext,
    ids: _AlertIds,
) -> None:
    bus.publish(
        _deadline_envelope(
            alerted,
            event_id=ids.mutation_id,
            event_type="deadline.updated",
            correlation_id=context.correlation_id,
            device_id=ids.device_id,
        ),
        commit_state=lambda: store.update(alerted),
    )
    bus.publish(
        EventEnvelope(
            event_id=ids.fact_id,
            type="deadline.approaching",
            occurred_at=ids.occurred_at,
            principal=DEADLINES_PRINCIPAL,
            correlation_id=context.correlation_id,
            causation_id=ids.mutation_id,  # 15 §5.1: the direct parent
            device_id=ids.device_id,
            payload={
                "deadline_id": alerted.id,
                "title": alerted.title,
                "at": alerted.at,
            },
            recovery_grade=False,
            entity_refs=({"kind": "deadline", "id": alerted.id},),
        ),
        # No state of its own: the mutation above already committed. A pure
        # fact's whole existence IS the event (EB-008 rule 2).
        commit_state=lambda: None,
    )


def make_deadline_sweep_handler(
    bus: EventBus,
    deadline_store: DeadlineStore,
    clock: Clock,
    new_id: Callable[[], str],
    device_id: str,
) -> Handler:
    """The lead-time sweep (FR-031): every tracked deadline whose lead
    threshold has been crossed transitions `tracked → alerted` and announces
    itself. See the ordering ruling above `_publish_deadline_alert`."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        now = clock.now()
        alerted: list[str] = []
        for deadline in deadline_store.active():
            if not due_lead_thresholds(deadline, now):
                continue
            transitioned = mark_alerted(deadline)
            _publish_deadline_alert(
                bus,
                deadline_store,
                transitioned,
                context,
                _AlertIds(
                    mutation_id=new_id(),
                    fact_id=new_id(),
                    occurred_at=now.isoformat(),
                    device_id=device_id,
                ),
            )
            alerted.append(transitioned.id)
        return {"alerted": alerted, "count": len(alerted)}

    return handler


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


def make_notification_ack_handler(
    notification_store: NotificationStore, clock: Clock
) -> Handler:
    """`notification.ack` (12 §13): acking is a command, and it is additive
    — it stamps `acked_at` and never deletes history."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        notification_id = params.get("id")
        if not isinstance(notification_id, str) or not notification_id:
            raise ApiError("invalid_request", "notification.ack requires an 'id'")
        try:
            acked = notification_store.ack(notification_id, clock.now())
        except NotificationNotFoundError as exc:
            raise ApiError("not_found", f"no notification {notification_id}") from exc
        return {"id": acked.id, "state": acked.state}

    return handler


def make_held_action_approve_handler(
    held_actions: HeldActionStore, clock: Clock
) -> Handler:
    """`held_action.approve` (ADR-001 Decision #5: itself idempotent —
    double-approval returns the cached outcome via API-004, already covered
    generically by the dispatcher's idempotency store, not repeated here;
    ADR-002: `first_party_only`, enforced by the dispatcher's channel check
    before this handler ever runs — a plugin session cannot reach this
    code path at all).

    Transitions `pending -> approved` only. Driving the approved effect to
    `executed` (ADR-001 Decision #3) needs the held operation's original
    params to replay it — `held_action`'s schema carries `operation` (the
    registry name) and `action` (a free-text description), never the
    params themselves (`migrations/0005_held_action_lifecycle.sql`,
    `domain/ports/held_action.py`). That's a real, named gap — ADR-001's
    own Consequences section calls the schema delta "owed... applied by
    the follow-through PR", not something to invent here. It is also
    moot today: no operation currently registered is on 05_AGENTS
    Appendix D's closed list, so nothing live produces a held action to
    drive in the first place. This handler serves the transition that IS
    buildable now; `approved_not_executed()`'s redrive sweep and the
    effect-driving half remain open, not silently completed.
    """

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        held_action_id = params.get("id")
        if not isinstance(held_action_id, str) or not held_action_id:
            raise ApiError("invalid_request", "held_action.approve requires an 'id'")
        try:
            approved = held_actions.approve(held_action_id, clock.now().isoformat())
        except HeldActionExpired as exc:
            raise ApiError(
                "conflict", f"held action {held_action_id} has expired"
            ) from exc
        except HeldActionNotFound as exc:
            # The store raises this both for a genuinely absent id and for
            # one not currently `pending` (its message names which) — the
            # real contract, not tightened into two distinct codes here.
            raise ApiError("not_found", str(exc)) from exc
        return {"id": approved.id, "status": approved.status}

    return handler


def make_held_action_cancel_handler(held_actions: HeldActionStore) -> Handler:
    """`held_action.cancel` (ADR-002: `first_party_only`, dispatcher-enforced
    before this handler runs). Transitions `pending -> cancelled` — Kang
    declining is final, the same terminal state the 24h expiry sweep
    (`HeldActionStore.expire_due`, not wired to a job yet) would also
    produce."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        held_action_id = params.get("id")
        if not isinstance(held_action_id, str) or not held_action_id:
            raise ApiError("invalid_request", "held_action.cancel requires an 'id'")
        try:
            cancelled = held_actions.cancel(held_action_id)
        except HeldActionNotFound as exc:
            raise ApiError("not_found", str(exc)) from exc
        return {"id": cancelled.id, "status": cancelled.status}

    return handler


def make_held_action_list_handler(held_actions: HeldActionStore) -> Handler:
    """`held_action.list` (added 2026-08-05, dashboard Zone 2's approval
    queue + the confirm dialog, 09_UI §4/§7): every `pending` held action,
    oldest first — `HeldActionStore.pending()`'s existing contract,
    exposed through the API for the first time. Mirrors the dataclass
    directly (id/operation/action/principal/reason/reversibility/
    correlation_id/created_at/expires_at/status): unlike `deadline.list`,
    there is no separate "full replay payload" to distinguish from here —
    `HeldAction`'s fields already are exactly 12_API §7's dialog
    contents, nothing more to trim."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "held_actions": [
                {
                    "id": a.id,
                    "operation": a.operation,
                    "action": a.action,
                    "principal": a.principal,
                    "reason": a.reason,
                    "reversibility": a.reversibility,
                    "correlation_id": a.correlation_id,
                    "created_at": a.created_at,
                    "expires_at": a.expires_at,
                    "status": a.status,
                }
                for a in held_actions.pending()
            ]
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


def make_permission_list_handler(engine: PermissionEngine) -> Handler:
    """`permission.list` (09_UI §7: "every grant per principal, in the same
    scope language as permissions.toml, with plain-language consequence
    lines"). Read-only reflection of `PermissionEngine.snapshot()` — the
    same loaded grant snapshot every permission check in this Core runs
    against, not a fresh re-read of the file (which could diverge from
    what's actually enforced if the file changed since boot)."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "grants": [
                {
                    "principal": principal,
                    "scopes": [
                        {"scope": scope, "consequence": _scope_consequence(scope)}
                        for scope in scopes
                    ],
                }
                for principal, scopes in engine.snapshot().items()
            ]
        }

    return handler


def make_audit_list_handler(audit: AuditService, clock: Clock) -> Handler:
    """`audit.list` (added 2026-08-05, System-domain Activity view, 09_UI
    §12): every audit record of one month, oldest first —
    `AuditService.records()`'s existing pass-through over the `AuditLog`
    port, exposed through the API for the first time. `month` defaults to
    the injected clock's current month, mirroring `plan.generate`'s own
    default-to-today convention."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        month = params.get("month") or clock.now().strftime("%Y-%m")
        return {
            "month": month,
            "records": [
                {
                    "at": record.entry.at,
                    "principal": record.entry.principal,
                    "action": record.entry.action,
                    "correlation_id": record.entry.correlation_id,
                    "details": record.entry.details,
                }
                for record in audit.records(month)
            ],
        }

    return handler


def make_system_health_handler(job_store: JobStore, kill_switch: KillSwitch) -> Handler:
    """`system.health` (added 2026-08-05, System-domain Health view, 09_UI
    §12): job statuses + the automation kill-switch state.
    `JobStore.list_jobs()`/`.consecutive_failures()` and `KillSwitch.
    is_engaged()` already existed — pure API-layer exposure, no new
    domain logic. Backup age, restore-verification, index parity, and the
    integrity-incident counter are NOT covered (see this operation's
    schema docstring for why) — a real, named gap, not silently folded
    into "Health built."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "jobs": [
                {
                    "id": job.id,
                    "name": job.name,
                    "schedule": job.schedule,
                    "catch_up": job.catch_up,
                    "enabled": job.enabled,
                    "quarantined": job.quarantined,
                    "consecutive_failures": job_store.consecutive_failures(job.id),
                }
                for job in job_store.list_jobs()
            ],
            "automation_engaged": kill_switch.is_engaged(),
        }

    return handler


def make_invocation_list_handler(invocations: InvocationStore) -> Handler:
    """`invocation.list` (added 2026-08-05, System-domain Invocations view,
    09_UI §12): the `limit` most recent invocations, newest-`started`-first
    — `InvocationStore.recent()`, new port surface (unlike `deadline.list`/
    `held_action.list`/`audit.list`, `InvocationStore` had no list method
    at all before this). `limit` defaults to `DEFAULT_LIMIT` and clamps to
    `MAX_LIMIT` (12_API §15's standing "default page 50, max 500") rather
    than raising `invalid_request` on an over-large value — a clamp is the
    same shape `plan.generate`'s date-default and `audit.list`'s month-
    default already use for "no value supplied," and an over-large `limit`
    is a client asking for more than the standing cap allows, not a
    malformed request."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        requested = params.get("limit")
        # max(1, ...): SQLite's LIMIT -1 (or 0) means "unlimited" — clamping
        # only the top end would let a non-positive `limit` defeat the
        # entire point of a bounded page.
        limit = (
            DEFAULT_LIMIT if requested is None else max(1, min(requested, MAX_LIMIT))
        )
        return {
            "invocations": [
                {
                    "id": inv.id,
                    "correlation_id": inv.correlation_id,
                    "kind": inv.kind,
                    "operation": inv.operation,
                    "principal": inv.principal,
                    "trigger": inv.trigger,
                    "started": inv.started,
                    "finished": inv.finished,
                    "outcome": inv.outcome,
                }
                for inv in invocations.recent(limit)
            ]
        }

    return handler
