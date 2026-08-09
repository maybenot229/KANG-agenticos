"""project.create / project.list / .complete handlers.

Layer: api.
Constitutional home: 12_API §2/§7/§8, ADR-013 (project.created — the
Projects domain's first write path), ADR-018 (project.complete — the
entity's first status transition).
"""

from __future__ import annotations

from typing import Any, Callable

from kang.api.dispatch import Handler, HandlerContext
from kang.api.errors import ApiError
from kang.domain.ports.clock import Clock
from kang.domain.ports.eventlog import EventEnvelope
from kang.domain.ports.project_store import (
    ProjectNotFoundError,
    ProjectRevisionConflictError,
    ProjectStore,
)
from kang.domain.projects.project_service import (
    ProjectDraft,
    ProjectValidationError,
    complete_project,
    create_project,
    project_event_payload,
)
from kang.kernel.bus.bus import EventBus

__all__ = [
    "PROJECTS_PRINCIPAL",
    "make_project_complete_handler",
    "make_project_create_handler",
    "make_project_list_handler",
]

PROJECTS_PRINCIPAL = "kernel:projects"  # owns project truth (EB-010, ADR-013)


def make_project_create_handler(
    bus: EventBus,
    project_store: ProjectStore,
    clock: Clock,
    new_id: Callable[[], str],
    device_id: str,
) -> Handler:
    """`project.create` (ADR-013): the Projects domain's first write path —
    tracking only, mirrors `make_deadline_create_handler`'s exact shape.
    Publishes `project.created` (recovery-grade, full row) under
    `kernel:projects` (EB-010: the domain service publishes, not the
    requester) — `commit_state` only runs inside `bus.publish` (EB-004),
    so this is the only way the write can commit at all."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        try:
            project = create_project(
                ProjectDraft(
                    name=params.get("name", ""),
                    description=params.get("description"),
                    status=params.get("status", "active"),
                    vault_folder=params.get("vault_folder"),
                    github_repo=params.get("github_repo"),
                    goal_id=params.get("goal_id"),
                ),
                project_id=new_id(),
                clock=clock,
                device_id=device_id,
            )
        except ProjectValidationError as exc:
            raise ApiError("invalid_request", str(exc)) from exc
        bus.publish(
            EventEnvelope(
                event_id=new_id(),
                type="project.created",
                occurred_at=project.updated_at.isoformat(),
                principal=PROJECTS_PRINCIPAL,
                correlation_id=context.correlation_id,
                device_id=device_id,
                payload=project_event_payload(project),
                recovery_grade=True,
                entity_refs=({"kind": "project", "id": project.id},),
            ),
            commit_state=lambda: project_store.create(project),
        )
        return {"project_id": project.id, "revision": project.revision}

    return handler


def make_project_complete_handler(
    bus: EventBus,
    project_store: ProjectStore,
    clock: Clock,
    new_id: Callable[[], str],
    device_id: str,
) -> Handler:
    """`project.complete` (ADR-018): `active -> completed`. Mirrors
    `make_task_complete_handler`'s exact shape: fetch, transition,
    publish `project.updated` under `kernel:projects`, commit via
    `ProjectStore.update()`'s optimistic-concurrency contract."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        project_id = params.get("id")
        if not isinstance(project_id, str) or not project_id:
            raise ApiError("invalid_request", "project.complete requires an 'id'")
        try:
            project = project_store.get(project_id)
        except ProjectNotFoundError as exc:
            raise ApiError("not_found", f"no project {project_id}") from exc
        try:
            completed = complete_project(project, clock)
        except ProjectValidationError as exc:
            raise ApiError("invalid_request", str(exc)) from exc

        committed_box: list = []

        def _commit() -> None:
            committed_box.append(project_store.update(completed))

        try:
            bus.publish(
                EventEnvelope(
                    event_id=new_id(),
                    type="project.updated",
                    occurred_at=completed.updated_at.isoformat(),
                    principal=PROJECTS_PRINCIPAL,
                    correlation_id=context.correlation_id,
                    device_id=device_id,
                    payload=project_event_payload(completed),
                    recovery_grade=True,
                    entity_refs=({"kind": "project", "id": completed.id},),
                ),
                commit_state=_commit,
            )
        except ProjectRevisionConflictError as exc:
            current = project_store.get(project_id)
            raise ApiError(
                "conflict",
                f"project {project_id} changed since it was read",
                details={"current_revision": current.revision},
            ) from exc

        committed = committed_box[0]
        return {"project_id": committed.id, "revision": committed.revision}

    return handler


def make_project_list_handler(project_store: ProjectStore) -> Handler:
    """`project.list` (ADR-013, tracking only): every project, name-then-id
    ordered — `ProjectStore.list_all()`'s existing contract, exposed
    verbatim. No new domain logic."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "projects": [
                {
                    "id": p.id,
                    "name": p.name,
                    "status": p.status,
                    "description": p.description,
                    "vault_folder": p.vault_folder,
                    "github_repo": p.github_repo,
                    "goal_id": p.goal_id,
                }
                for p in project_store.list_all()
            ]
        }

    return handler
