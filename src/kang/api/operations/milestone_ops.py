"""milestone.create / milestone.list / .reach / .miss / .drop handlers.

Layer: api.
Constitutional home: 12_API §2/§7/§8, ADR-015 (milestone.created — the
Milestones sub-domain's first write path), ADR-018 (.reach/.miss/.drop —
the entity's first status transitions, publishing milestone.updated).
"""

from __future__ import annotations

from typing import Any, Callable

from kang.api.dispatch import Handler, HandlerContext
from kang.api.errors import ApiError
from kang.domain.ports.clock import Clock
from kang.domain.ports.eventlog import EventEnvelope
from kang.domain.ports.milestone_store import (
    MilestoneNotFoundError,
    MilestoneRevisionConflictError,
    MilestoneStore,
)
from kang.domain.projects.milestone_service import (
    MilestoneDraft,
    MilestoneValidationError,
    create_milestone,
    mark_dropped,
    mark_missed,
    mark_reached,
    milestone_event_payload,
)
from kang.kernel.bus.bus import EventBus

__all__ = [
    "MILESTONES_PRINCIPAL",
    "make_milestone_create_handler",
    "make_milestone_drop_handler",
    "make_milestone_list_handler",
    "make_milestone_miss_handler",
    "make_milestone_reach_handler",
]

MILESTONES_PRINCIPAL = "kernel:milestones"  # owns milestone truth (EB-010, ADR-015)


def make_milestone_create_handler(
    bus: EventBus,
    milestone_store: MilestoneStore,
    clock: Clock,
    new_id: Callable[[], str],
    device_id: str,
) -> Handler:
    """`milestone.create` (ADR-015): the Milestones sub-domain's first
    write path — tracking only, mirrors `make_project_create_handler`'s
    exact shape. Publishes `milestone.created` (recovery-grade, full row)
    under `kernel:milestones` — `commit_state` only runs inside
    `bus.publish` (EB-004), so this is the only way the write can commit
    at all. An unknown `project_id` surfaces as `invalid_request` via the
    database's own FK constraint, not duplicated as a domain check
    (`milestone_service.py::create_milestone`'s own docstring)."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        try:
            milestone = create_milestone(
                MilestoneDraft(
                    project_id=params.get("project_id", ""),
                    title=params.get("title", ""),
                    due=params.get("due"),
                    status=params.get("status", "pending"),
                ),
                milestone_id=new_id(),
                clock=clock,
                device_id=device_id,
            )
        except MilestoneValidationError as exc:
            raise ApiError("invalid_request", str(exc)) from exc
        # An unknown project_id surfaces as whatever the database's own FK
        # constraint raises (sqlite3.IntegrityError) — not translated to a
        # distinct ApiError here. Matches every other FK-bearing create
        # handler in this codebase (deadline.create's project_id/
        # competition_id are the same shape); a local deviation for
        # milestone alone would be inconsistent, not an improvement.
        bus.publish(
            EventEnvelope(
                event_id=new_id(),
                type="milestone.created",
                occurred_at=milestone.updated_at.isoformat(),
                principal=MILESTONES_PRINCIPAL,
                correlation_id=context.correlation_id,
                device_id=device_id,
                payload=milestone_event_payload(milestone),
                recovery_grade=True,
                entity_refs=(
                    {"kind": "milestone", "id": milestone.id},
                    {"kind": "project", "id": milestone.project_id},
                ),
            ),
            commit_state=lambda: milestone_store.create(milestone),
        )
        return {"milestone_id": milestone.id, "revision": milestone.revision}

    return handler


def _make_milestone_transition_handler(
    transition,
    bus: EventBus,
    milestone_store: MilestoneStore,
    clock: Clock,
    new_id: Callable[[], str],
    device_id: str,
) -> Handler:
    """Shared shape behind `.reach`/`.miss`/`.drop` (ADR-018): fetch,
    transition, publish `milestone.updated` under `kernel:milestones`,
    commit via the store's optimistic-concurrency `update()` — mirrors
    `make_task_complete_handler`'s exact shape. `transition` is one of
    `mark_reached`/`mark_missed`/`mark_dropped`."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        milestone_id = params.get("id")
        if not isinstance(milestone_id, str) or not milestone_id:
            raise ApiError("invalid_request", "requires an 'id'")
        try:
            milestone = milestone_store.get(milestone_id)
        except MilestoneNotFoundError as exc:
            raise ApiError("not_found", f"no milestone {milestone_id}") from exc
        try:
            transitioned = transition(milestone, clock)
        except MilestoneValidationError as exc:
            raise ApiError("invalid_request", str(exc)) from exc

        committed_box: list = []

        def _commit() -> None:
            committed_box.append(milestone_store.update(transitioned))

        try:
            bus.publish(
                EventEnvelope(
                    event_id=new_id(),
                    type="milestone.updated",
                    occurred_at=transitioned.updated_at.isoformat(),
                    principal=MILESTONES_PRINCIPAL,
                    correlation_id=context.correlation_id,
                    device_id=device_id,
                    payload=milestone_event_payload(transitioned),
                    recovery_grade=True,
                    entity_refs=(
                        {"kind": "milestone", "id": transitioned.id},
                        {"kind": "project", "id": transitioned.project_id},
                    ),
                ),
                commit_state=_commit,
            )
        except MilestoneRevisionConflictError as exc:
            current = milestone_store.get(milestone_id)
            raise ApiError(
                "conflict",
                f"milestone {milestone_id} changed since it was read",
                details={"current_revision": current.revision},
            ) from exc

        committed = committed_box[0]
        return {"milestone_id": committed.id, "revision": committed.revision}

    return handler


def make_milestone_reach_handler(
    bus: EventBus,
    milestone_store: MilestoneStore,
    clock: Clock,
    new_id: Callable[[], str],
    device_id: str,
) -> Handler:
    """`milestone.reach` (ADR-018): `pending -> reached`."""
    return _make_milestone_transition_handler(
        mark_reached, bus, milestone_store, clock, new_id, device_id
    )


def make_milestone_miss_handler(
    bus: EventBus,
    milestone_store: MilestoneStore,
    clock: Clock,
    new_id: Callable[[], str],
    device_id: str,
) -> Handler:
    """`milestone.miss` (ADR-018): `pending -> missed`."""
    return _make_milestone_transition_handler(
        mark_missed, bus, milestone_store, clock, new_id, device_id
    )


def make_milestone_drop_handler(
    bus: EventBus,
    milestone_store: MilestoneStore,
    clock: Clock,
    new_id: Callable[[], str],
    device_id: str,
) -> Handler:
    """`milestone.drop` (ADR-018): `pending -> dropped`."""
    return _make_milestone_transition_handler(
        mark_dropped, bus, milestone_store, clock, new_id, device_id
    )


def make_milestone_list_handler(milestone_store: MilestoneStore) -> Handler:
    """`milestone.list` (ADR-015, tracking only): every milestone for one
    project, due-then-id ordered — `MilestoneStore.list_for_project()`'s
    existing contract, exposed verbatim. No new domain logic."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        project_id = params.get("project_id")
        if not isinstance(project_id, str) or not project_id:
            raise ApiError("invalid_request", "milestone.list requires a 'project_id'")
        return {
            "milestones": [
                {
                    "id": m.id,
                    "project_id": m.project_id,
                    "title": m.title,
                    "status": m.status,
                    "due": m.due,
                }
                for m in milestone_store.list_for_project(project_id)
            ]
        }

    return handler
