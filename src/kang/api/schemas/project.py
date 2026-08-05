"""Request/response schemas for project.* operations (ADR-010 Ruling 1).

Layer: api.
Constitutional home: 12_API §2, ADR-013 (project.created — the entity's
first write path). Mirrors `deadline.py`'s own shape: schemas describe the
real contract as the handler already behaves, not a wish list.

Tracking only (03_ROADMAP M4/M5): `project.create` + `project.list`,
nothing more this pass — no `project.get`/`.update` operation exists yet
(mirrors `deadline.py`'s own precedent of not schema-ing ahead of a real
handler).
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator

from kang.domain.ports.project_store import PROJECT_STATUSES

__all__ = [
    "ProjectCreateRequest",
    "ProjectCreateResponse",
    "ProjectListItem",
    "ProjectListRequest",
    "ProjectListResponse",
]


class ProjectCreateRequest(BaseModel):
    """`project.create` params (operations.py::make_project_create_handler).
    `name` defaults to `""`, which the domain layer then rejects — matching
    `DeadlineCreateRequest`'s own documented convention (an omitted required
    field already produces `invalid_request` today; this schema doesn't
    change that behavior, just describes it)."""

    name: str = ""
    description: str | None = None
    status: str = "active"
    vault_folder: str | None = None
    github_repo: str | None = None
    goal_id: str | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank_after_strip(cls, value: str) -> str:
        # Mirrors project_service.py::_validate's `not draft.name.strip()`.
        if not value.strip():
            raise ValueError("name must be non-empty")
        return value

    @field_validator("status")
    @classmethod
    def _status_is_known(cls, value: str) -> str:
        # Mirrors project_service.py::_validate's status-enum check.
        if value not in PROJECT_STATUSES:
            raise ValueError(f"status must be one of {PROJECT_STATUSES}")
        return value


class ProjectCreateResponse(BaseModel):
    """`project.create` result (operations.py::make_project_create_handler)."""

    project_id: str
    revision: int


class ProjectListRequest(BaseModel):
    """`project.list` params (operations.py::make_project_list_handler). No
    fields: the handler takes none, mirroring `DeadlineListRequest`."""


class ProjectListItem(BaseModel):
    """One project as `project.list` renders it — every field
    `ProjectStore.list_all()` returns (tracking-only: there's no separate
    "full replay payload" to distinguish from here, unlike `deadline.list`,
    since nothing yet reads a narrower subset)."""

    id: str
    name: str
    status: str
    description: str | None = None
    vault_folder: str | None = None
    github_repo: str | None = None
    goal_id: str | None = None


class ProjectListResponse(BaseModel):
    """`project.list` result: every project, name-then-id ordered —
    `ProjectStore.list_all()`'s contract, exposed verbatim."""

    projects: list[ProjectListItem]
