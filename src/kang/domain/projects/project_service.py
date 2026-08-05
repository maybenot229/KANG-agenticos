"""Project domain service — invariants for the project entity.

Layer: domain/projects (capability service; deterministic, zero I/O).
Constitutional home: 07_DATABASE §5.2 (project shape, status enum);
ADR-013 (project.created, the entity's first write path).

Tracking only this pass: `create_project` is the entity's whole surface —
no status-transition function exists yet (mirrors deadline_service.py's
own precedent: build the transitions a real operation needs, not ahead of
one).
"""

from __future__ import annotations

from dataclasses import dataclass

from kang.domain.ports.clock import Clock
from kang.domain.ports.project_store import PROJECT_STATUSES, Project

__all__ = [
    "ProjectDraft",
    "ProjectValidationError",
    "create_project",
    "project_event_payload",
]


class ProjectValidationError(Exception):
    """A project invariant was violated. Raised before anything is
    persisted."""


@dataclass(frozen=True)
class ProjectDraft:
    """What Kang states about a new project; the system stamps the rest
    (11 §4: beyond four parameters, it's a dataclass)."""

    name: str
    description: str | None = None
    status: str = "active"
    vault_folder: str | None = None
    github_repo: str | None = None
    goal_id: str | None = None


def _validate(draft: ProjectDraft) -> None:
    if not draft.name.strip():
        raise ProjectValidationError("name must be non-empty")
    if draft.status not in PROJECT_STATUSES:
        raise ProjectValidationError(f"status must be one of {PROJECT_STATUSES}")


def create_project(
    draft: ProjectDraft, project_id: str, clock: Clock, device_id: str
) -> Project:
    """Build a valid new Project with the sync quartet stamped (D009):
    created_at/updated_at from the injected clock, device_id, revision 1."""
    _validate(draft)
    now = clock.now()
    return Project(
        id=project_id,
        name=draft.name,
        description=draft.description,
        status=draft.status,
        vault_folder=draft.vault_folder,
        github_repo=draft.github_repo,
        goal_id=draft.goal_id,
        created_at=now,
        updated_at=now,
        device_id=device_id,
        revision=1,
    )


def project_event_payload(project: Project) -> dict:
    """The self-sufficient project payload for `project.created` (EB-003,
    ADR-013): the full field set, so a recovery-grade replay reconstructs
    the row exactly. Mirrors `deadline_event_payload`/`task_event_payload`."""
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "vault_folder": project.vault_folder,
        "github_repo": project.github_repo,
        "goal_id": project.goal_id,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
        "device_id": project.device_id,
        "revision": project.revision,
    }
