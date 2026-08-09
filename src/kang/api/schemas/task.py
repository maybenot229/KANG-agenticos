"""Request/response schemas for task.* operations (ADR-010 Ruling 1).

Layer: api.
Constitutional home: 12_API §2 (the wire contract is the API layer's own
concern, distinct from domain representations — ADR-010 Ruling 1's 1A
bullet). Mirrors `domain/tasks/task_service.py`'s existing, already-enforced
invariants (title non-empty after stripping, priority 1-5) rather than
inventing new ones — these schemas describe the real contract as it already
behaves, they do not tighten it.

Proof-of-pattern pair for ADR-010's rollout (session 2026-07-31): the first
two operations to get real schemas, chosen as the simplest, most-obviously-
typed params among the currently-wired operations. Not yet attached to
dispatch validation (ADR-010 Ruling 4 is deliberately unimplemented this
session — see the session report; Ruling 4 landed for real in a later
session, exercised by every schema-attached operation since, this one
included).

`TaskCompleteRequest`/`TaskCompleteResponse` (added 2026-08-09): the
task entity's first status-transition operation — `done` is the one
transition it has (`complete_task`, `domain/tasks/task_service.py`),
mirroring `deadline.updated`'s existing `mark_alerted` pattern (fetch,
transition, publish under the domain's own principal, commit via the
store's existing optimistic-concurrency `update()`).
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator

__all__ = [
    "TaskCompleteRequest",
    "TaskCompleteResponse",
    "TaskCreateRequest",
    "TaskCreateResponse",
    "TaskGetRequest",
    "TaskGetResponse",
]


class TaskCreateRequest(BaseModel):
    """`task.create` params (operations.py::make_task_create_handler).
    `priority` bounds (1-5) mirror `domain/tasks/task_service.py::_validate`
    — an existing, already-enforced invariant, not a new one."""

    title: str
    priority: int = 3

    @field_validator("title")
    @classmethod
    def _title_not_blank_after_strip(cls, value: str) -> str:
        # Mirrors the handler's `not title.strip()` check exactly — the
        # schema must describe the real contract, never a stricter one.
        if not value.strip():
            raise ValueError("title must be non-empty")
        return value

    @field_validator("priority")
    @classmethod
    def _priority_in_domain_bounds(cls, value: int) -> int:
        # Mirrors domain/tasks/task_service.py::_validate's
        # `1 <= draft.priority <= 5` exactly.
        if not 1 <= value <= 5:
            raise ValueError("priority must be between 1 and 5")
        return value


class TaskCreateResponse(BaseModel):
    """`task.create` result (operations.py::make_task_create_handler)."""

    task_id: str
    revision: int


class TaskGetRequest(BaseModel):
    """`task.get` params (operations.py::make_task_get_handler). No
    non-empty constraint on `id`: the current handler only checks
    `isinstance(task_id, str)` — an empty string reaches `task_store.get`
    and surfaces as `not_found`, not `invalid_request`. Mirrored here
    exactly rather than tightened."""

    id: str


class TaskGetResponse(BaseModel):
    """`task.get` result (operations.py::make_task_get_handler)."""

    id: str
    title: str
    status: str
    priority: int
    revision: int


class TaskCompleteRequest(BaseModel):
    """`task.complete` params (operations.py::make_task_complete_handler).
    No non-empty constraint on `id`, mirroring `TaskGetRequest`'s own
    documented convention: an empty string reaches `task_store.get` and
    surfaces as `not_found`, not `invalid_request`."""

    id: str


class TaskCompleteResponse(BaseModel):
    """`task.complete` result
    (operations.py::make_task_complete_handler)."""

    task_id: str
    revision: int
    completed_at: str
