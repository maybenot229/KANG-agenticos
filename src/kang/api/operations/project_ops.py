"""project.create / project.list handlers.

Layer: api.
Constitutional home: 12_API §2/§7/§8, ADR-013 (project.created — the
Projects domain's first write path).
"""

from __future__ import annotations

from typing import Any, Callable

from kang.api.dispatch import Handler, HandlerContext
from kang.api.errors import ApiError
from kang.domain.ports.clock import Clock
from kang.domain.ports.eventlog import EventEnvelope
from kang.domain.ports.project_store import ProjectStore
from kang.domain.projects.project_service import (
    ProjectDraft,
    ProjectValidationError,
    create_project,
    project_event_payload,
)
from kang.kernel.bus.bus import EventBus

__all__ = [
    "PROJECTS_PRINCIPAL",
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
