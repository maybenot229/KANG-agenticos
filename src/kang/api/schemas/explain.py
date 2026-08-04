"""Request/response schemas for explain.* operations (ADR-010 Ruling 1).

Layer: api.
Constitutional home: 12_API §12, ADR-010 Ruling 1. Only `explain.invocation`
is populated — the other four registered `explain.*` operations
(`plan_item`, `notification`, `suggestion`, `memory`) are stub handlers
(`operations.py::make_explain_stub_handler`) that always return `not_found`
because their subjects don't exist yet (12 §12: "if reconstruction is
impossible... MUST NOT synthesize a narrative"). They were not part of this
roll-out's named operation list and are left `schema=None`, same as
`held_action.*` — attaching a schema to an always-failing stub would
describe a contract that doesn't exist yet.

`correlation_id`'s non-empty constraint mirrors the handler's exact
`not target` truthiness check (same pattern as `notification.ack`'s `id`).
Response fields are field-for-field against `Invocation`
(`domain/ports/invocation.py`) and `AuditEntry`'s exported shape, not
invented.

Roll-out session: 2026-07-31 (follow-up to the task.* proof-of-pattern).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "AuditChainEntry",
    "ExplainInvocationRequest",
    "ExplainInvocationResponse",
]


class ExplainInvocationRequest(BaseModel):
    """`explain.invocation` params
    (operations.py::make_explain_invocation_handler)."""

    correlation_id: str = Field(min_length=1)


class AuditChainEntry(BaseModel):
    """One `chain` entry in `explain.invocation`'s result — field-for-field
    against the handler's dict comprehension over `audit.records_for_correlation`
    (`action`, `principal`, `at` from `AuditEntry`; `details` is
    `dict[str, Any] | None` per `domain/ports/audit.py`)."""

    action: str
    principal: str
    at: str
    details: dict[str, Any] | None = None


class ExplainInvocationResponse(BaseModel):
    """`explain.invocation` result
    (operations.py::make_explain_invocation_handler), field-for-field
    against `Invocation` (`domain/ports/invocation.py`) plus the handler's
    own `chain` and `reconstructed_from` additions. `manifest`/`finished`/
    `outcome` are `None`-able exactly as `Invocation` declares them (null
    for non-agent operations / while running / before completion)."""

    correlation_id: str
    trigger: str
    operation: str
    principal: str
    kind: str
    manifest: str | None = None
    started: str
    finished: str | None = None
    outcome: str | None = None
    chain: list[AuditChainEntry]
    reconstructed_from: str
