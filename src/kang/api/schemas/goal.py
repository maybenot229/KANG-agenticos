"""Request/response schemas for goal.* operations (ADR-010 Ruling 1).

Layer: api.
Constitutional home: 12_API §2, ADR-016 (goal.created — the entity's
first write path). Mirrors `project.py`'s own shape: schemas describe the
real contract as the handler already behaves, not a wish list.

`goal.achieve`/`.revise`/`.retire` (ADR-018, 2026-08-09) are the entity's
first status transitions — `GoalTransitionRequest`/`Response` are shared
across all three (identical shape), not three near-duplicate schemas.
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator

from kang.domain.ports.goal_store import GOAL_HORIZONS, GOAL_STATUSES

__all__ = [
    "GoalCreateRequest",
    "GoalCreateResponse",
    "GoalListItem",
    "GoalListRequest",
    "GoalListResponse",
    "GoalTransitionRequest",
    "GoalTransitionResponse",
]


class GoalCreateRequest(BaseModel):
    """`goal.create` params (operations.py::make_goal_create_handler).
    `title`/`horizon` default to `""`, which the domain layer then rejects
    — matching `ProjectCreateRequest`'s own documented convention."""

    title: str = ""
    horizon: str = ""
    description: str | None = None
    status: str = "active"

    @field_validator("title")
    @classmethod
    def _title_not_blank_after_strip(cls, value: str) -> str:
        # Mirrors goal_service.py::_validate's `not draft.title.strip()`.
        if not value.strip():
            raise ValueError("title must be non-empty")
        return value

    @field_validator("horizon")
    @classmethod
    def _horizon_is_known(cls, value: str) -> str:
        # Mirrors goal_service.py::_validate's horizon-enum check.
        if value not in GOAL_HORIZONS:
            raise ValueError(f"horizon must be one of {GOAL_HORIZONS}")
        return value

    @field_validator("status")
    @classmethod
    def _status_is_known(cls, value: str) -> str:
        # Mirrors goal_service.py::_validate's status-enum check.
        if value not in GOAL_STATUSES:
            raise ValueError(f"status must be one of {GOAL_STATUSES}")
        return value


class GoalCreateResponse(BaseModel):
    """`goal.create` result (operations.py::make_goal_create_handler)."""

    goal_id: str
    revision: int


class GoalListRequest(BaseModel):
    """`goal.list` params (operations.py::make_goal_list_handler). No
    fields: the handler takes none, mirroring `ProjectListRequest`."""


class GoalListItem(BaseModel):
    """One goal as `goal.list` renders it — every field
    `GoalStore.list_all()` returns."""

    id: str
    title: str
    horizon: str
    status: str
    description: str | None = None


class GoalListResponse(BaseModel):
    """`goal.list` result: every goal, title-then-id ordered —
    `GoalStore.list_all()`'s contract, exposed verbatim."""

    goals: list[GoalListItem]


class GoalTransitionRequest(BaseModel):
    """`goal.achieve`/`.revise`/`.retire` params (ADR-018) — identical
    shape across all three, one schema shared rather than three
    near-duplicates. No non-empty constraint on `id`, mirroring
    `TaskCompleteRequest`'s own documented convention."""

    id: str


class GoalTransitionResponse(BaseModel):
    """`goal.achieve`/`.revise`/`.retire` result (ADR-018) — shared
    across all three, same reasoning as the request."""

    goal_id: str
    revision: int
