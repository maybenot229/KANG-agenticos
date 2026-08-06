"""Request/response schemas for competition.* operations (ADR-010 Ruling 1).

Layer: api.
Constitutional home: 12_API §2, ADR-014 (competition.created — the
entity's first write path). Mirrors `project.py`'s own shape.

Tracking only (03_ROADMAP M4/M5): `competition.create` + `.list`, nothing
more this pass. No `evaluation`/`result` field on create — those are
Phase 3's own write path (07 §5.2's comment; `CompetitionDraft`'s own
docstring says the same).
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator

from kang.domain.ports.competition_store import COMPETITION_STATUSES

__all__ = [
    "CompetitionCreateRequest",
    "CompetitionCreateResponse",
    "CompetitionListItem",
    "CompetitionListRequest",
    "CompetitionListResponse",
]


class CompetitionCreateRequest(BaseModel):
    """`competition.create` params
    (operations.py::make_competition_create_handler). `name` defaults to
    `""`, which the domain layer then rejects — matching
    `ProjectCreateRequest`'s own documented convention."""

    name: str = ""
    url: str | None = None
    status: str = "discovered"
    project_id: str | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank_after_strip(cls, value: str) -> str:
        # Mirrors competition_service.py::_validate's `not draft.name.strip()`.
        if not value.strip():
            raise ValueError("name must be non-empty")
        return value

    @field_validator("status")
    @classmethod
    def _status_is_known(cls, value: str) -> str:
        # Mirrors competition_service.py::_validate's status-enum check.
        if value not in COMPETITION_STATUSES:
            raise ValueError(f"status must be one of {COMPETITION_STATUSES}")
        return value


class CompetitionCreateResponse(BaseModel):
    """`competition.create` result
    (operations.py::make_competition_create_handler)."""

    competition_id: str
    revision: int


class CompetitionListRequest(BaseModel):
    """`competition.list` params
    (operations.py::make_competition_list_handler). No fields."""


class CompetitionListItem(BaseModel):
    """One competition as `competition.list` renders it — every field
    `CompetitionStore.list_all()` returns."""

    id: str
    name: str
    status: str
    url: str | None = None
    evaluation: str | None = None
    result: str | None = None
    project_id: str | None = None


class CompetitionListResponse(BaseModel):
    """`competition.list` result: every competition, name-then-id
    ordered — `CompetitionStore.list_all()`'s contract, exposed verbatim."""

    competitions: list[CompetitionListItem]
