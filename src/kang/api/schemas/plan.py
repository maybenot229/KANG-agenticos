"""Request/response schemas for plan.* operations (ADR-010 Ruling 1).

Layer: api.
Constitutional home: 12_API §2, ADR-010 Ruling 1. `plan_date` mirrors
`operations.py::make_plan_generate_handler` exactly: the handler reads
`params.get("plan_date") or <today>`, with no format validation of its own
— so this schema does not validate the format either (11 §25: describe
the real contract, never a stricter one).

Roll-out session: 2026-07-31 (follow-up to the task.* proof-of-pattern).
"""

from __future__ import annotations

from pydantic import BaseModel

__all__ = [
    "PlanGenerateRequest",
    "PlanGenerateResponse",
]


class PlanGenerateRequest(BaseModel):
    """`plan.generate` params (operations.py::make_plan_generate_handler).
    `plan_date` is optional — an omitted value defaults to the injected
    clock's today, exactly as the handler does with `params.get(...) or
    ...`."""

    plan_date: str | None = None


class PlanGenerateResponse(BaseModel):
    """`plan.generate` result (operations.py::make_plan_generate_handler),
    field-for-field against the handler's return dict."""

    plan_date: str
    quest_ids: list[str]
    deadline_ids: list[str]
    calendar_event_ids: list[str]
    estimated_minutes: int
    deferred_count: int
    stamped: list[str]
