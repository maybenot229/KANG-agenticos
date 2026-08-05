"""Request/response schemas for deadline.* operations (ADR-010 Ruling 1).

Layer: api.
Constitutional home: 12_API §2, ADR-010 Ruling 1. Mirrors
`domain/deadlines/deadline_service.py`'s existing, already-enforced
invariants (title non-empty after stripping, `at` ISO-8601, `kind` in the
exported `DEADLINE_KINDS` enum) rather than inventing new ones — these
schemas describe the real contract as it already behaves.

**Deliberately NOT mirrored:** the domain's competition/project anchoring
rule (`_validate`'s "a {kind} deadline must reference a competition or a
project unless it's a self-standing kind"). That rule's kind list
(`_SELF_STANDING_KINDS`) is a private module-level constant in
`deadline_service.py`, not exported via `__all__` — importing it here would
violate 11 §5's "a module's public surface is its `__all__`; everything
else is private and MUST NOT be imported across packages" rule. Duplicating
the literal tuple instead risks silent drift if the domain module ever
changes it. Left enforced at the domain layer only, exactly as it already
is today — this is a real, deliberate scope limit, not an oversight (see
the session report's NOTES).

Also NOT read from `deadline.create`'s params today: `lead_days`. The
handler (`operations.py::make_deadline_create_handler`) never reads
`params.get("lead_days")` — the domain draft's default is always used.
Mirrored by omission: this schema does not accept a field the real handler
does not read.

Roll-out session: 2026-07-31 (follow-up to the task.* proof-of-pattern).
`DeadlineListRequest`/`Item`/`Response` added 2026-08-05 for the dashboard's
Zone 2 (09_UI §4) — exposing `DeadlineStore.active()`, an existing read
already used internally by `deadline_sweep` and `plan.generate`, through the
API for the first time. No new domain logic.
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator

from kang.domain.ports.deadline_store import DEADLINE_KINDS

__all__ = [
    "DeadlineCreateRequest",
    "DeadlineCreateResponse",
    "DeadlineListItem",
    "DeadlineListRequest",
    "DeadlineListResponse",
    "DeadlineSweepRequest",
    "DeadlineSweepResponse",
]


class DeadlineCreateRequest(BaseModel):
    """`deadline.create` params (operations.py::make_deadline_create_handler).
    Defaults mirror the handler's own `params.get(..., default)` calls
    exactly — including that an omitted `title`/`at` defaults to `""`,
    which the domain layer then rejects (matching today's real behavior:
    omitting them already produces `invalid_request`, not a different
    failure)."""

    title: str = ""
    at: str = ""
    kind: str = "custom"
    competition_id: str | None = None
    project_id: str | None = None

    @field_validator("title")
    @classmethod
    def _title_not_blank_after_strip(cls, value: str) -> str:
        # Mirrors deadline_service.py::_validate's `not draft.title.strip()`.
        if not value.strip():
            raise ValueError("title must be non-empty")
        return value

    @field_validator("at")
    @classmethod
    def _at_is_iso8601(cls, value: str) -> str:
        # Mirrors deadline_service.py::_parse_at exactly (same stdlib call,
        # same failure condition — not a stricter check).
        from datetime import datetime

        try:
            datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"deadline `at` must be ISO-8601, got {value!r}") from exc
        return value

    @field_validator("kind")
    @classmethod
    def _kind_is_known(cls, value: str) -> str:
        # Mirrors deadline_service.py::_validate's `draft.kind not in
        # DEADLINE_KINDS` — the exported enum, not the private
        # self-standing-kinds subset (see module docstring).
        if value not in DEADLINE_KINDS:
            raise ValueError(f"kind must be one of {DEADLINE_KINDS}")
        return value


class DeadlineCreateResponse(BaseModel):
    """`deadline.create` result (operations.py::make_deadline_create_handler)."""

    deadline_id: str
    revision: int


class DeadlineSweepRequest(BaseModel):
    """`deadline.sweep` params (operations.py::make_deadline_sweep_handler).
    The handler ignores `params` entirely — no fields to accept. Pydantic's
    default `extra='ignore'` behavior means unexpected keys are silently
    dropped here too, matching the handler exactly."""


class DeadlineSweepResponse(BaseModel):
    """`deadline.sweep` result (operations.py::make_deadline_sweep_handler)."""

    alerted: list[str]
    count: int


class DeadlineListRequest(BaseModel):
    """`deadline.list` params (operations.py::make_deadline_list_handler). No
    fields: the handler takes none, mirroring `DeadlineSweepRequest`."""


class DeadlineListItem(BaseModel):
    """One deadline as `deadline.list` renders it — the dashboard's Zone 2
    horizon fields, not the full row (`deadline_event_payload`'s full shape
    is for event replay, a different concern; mirrors `task.get`'s
    hand-picked-fields convention, not the create/event payload's)."""

    id: str
    title: str
    at: str
    kind: str
    status: str
    competition_id: str | None = None
    project_id: str | None = None


class DeadlineListResponse(BaseModel):
    """`deadline.list` result: every `tracked` deadline, soonest first —
    `DeadlineStore.active()`'s existing contract (`domain/ports/
    deadline_store.py`), exposed through the API for the first time. Added
    2026-08-05 for the dashboard's Zone 2 (09_UI §4); no domain logic
    changed — `active()` already existed and was already used by
    `deadline_sweep` and `plan.generate`."""

    deadlines: list[DeadlineListItem]
