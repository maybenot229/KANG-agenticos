"""Request/response schemas for milestone.* operations (ADR-010 Ruling 1).

Layer: api.
Constitutional home: 12_API §2, ADR-015 (milestone.created — the entity's
first write path). Mirrors `project.py`'s own shape.

Tracking only (ADR-015): `milestone.create` + `.list`, nothing more this
pass. `.list` is scoped by `project_id` — milestones have no meaningful
cross-project listing (a milestone without its project is not addressable
context; the port itself only offers `list_for_project`).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator

from kang.domain.ports.milestone_store import MILESTONE_STATUSES

__all__ = [
    "MilestoneCreateRequest",
    "MilestoneCreateResponse",
    "MilestoneListItem",
    "MilestoneListRequest",
    "MilestoneListResponse",
    "MilestoneTransitionRequest",
    "MilestoneTransitionResponse",
]


class MilestoneCreateRequest(BaseModel):
    """`milestone.create` params
    (operations.py::make_milestone_create_handler). `project_id`/`title`
    default to `""`, which the domain layer then rejects — matching
    `ProjectCreateRequest`'s own documented convention."""

    project_id: str = ""
    title: str = ""
    due: str | None = None
    status: str = "pending"

    @field_validator("project_id")
    @classmethod
    def _project_id_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("project_id must be non-empty")
        return value

    @field_validator("title")
    @classmethod
    def _title_not_blank_after_strip(cls, value: str) -> str:
        # Mirrors milestone_service.py::_validate's `not draft.title.strip()`.
        if not value.strip():
            raise ValueError("title must be non-empty")
        return value

    @field_validator("due")
    @classmethod
    def _due_is_iso8601_if_present(cls, value: str | None) -> str | None:
        # Mirrors milestone_service.py::_validate's ISO-8601 check.
        if value is None:
            return value
        try:
            datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                f"milestone `due` must be ISO-8601, got {value!r}"
            ) from exc
        return value

    @field_validator("status")
    @classmethod
    def _status_is_known(cls, value: str) -> str:
        # Mirrors milestone_service.py::_validate's status-enum check.
        if value not in MILESTONE_STATUSES:
            raise ValueError(f"status must be one of {MILESTONE_STATUSES}")
        return value


class MilestoneCreateResponse(BaseModel):
    """`milestone.create` result
    (operations.py::make_milestone_create_handler)."""

    milestone_id: str
    revision: int


class MilestoneListRequest(BaseModel):
    """`milestone.list` params (operations.py::make_milestone_list_handler).
    `project_id` is required — milestones are always listed within a
    project, never globally (see module docstring)."""

    project_id: str = ""

    @field_validator("project_id")
    @classmethod
    def _project_id_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("project_id must be non-empty")
        return value


class MilestoneListItem(BaseModel):
    """One milestone as `milestone.list` renders it — every field
    `MilestoneStore.list_for_project()` returns."""

    id: str
    project_id: str
    title: str
    status: str
    due: str | None = None


class MilestoneListResponse(BaseModel):
    """`milestone.list` result: every milestone for the requested project,
    due-date-then-id ordered (undated last) —
    `MilestoneStore.list_for_project()`'s contract, exposed verbatim."""

    milestones: list[MilestoneListItem]


class MilestoneTransitionRequest(BaseModel):
    """`milestone.reach`/`.miss`/`.drop` params (ADR-018) — identical
    shape across all three, one schema shared rather than three
    near-duplicates. No non-empty constraint on `id`, mirroring
    `TaskCompleteRequest`'s own documented convention: an empty string
    reaches the store and surfaces as `not_found`, not `invalid_request`."""

    id: str


class MilestoneTransitionResponse(BaseModel):
    """`milestone.reach`/`.miss`/`.drop` result (ADR-018) — shared across
    all three, same reasoning as the request."""

    milestone_id: str
    revision: int
