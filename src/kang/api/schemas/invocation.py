"""Request/response schemas for `invocation.list` (ADR-010 Ruling 1).

Layer: api.
Constitutional home: 09_UI §12 ("Invocations: the agent run history
(`invocation` table): outcome badges, durations, costs; each row opens
`kang explain`"). Added 2026-08-05 — `InvocationStore` had no list
capability at all (only `by_correlation`, a point lookup); `recent()` is
new port surface (`domain/ports/invocation.py`), not pure exposure like
`deadline.list`/`held_action.list`/`audit.list` before it.

No `manifest` field here: the list is the run-history overview, not the
reconstruction — `explain.invocation {correlation_id}` (already built)
is where a row's full manifest/audit chain lives, one click away exactly
as 09_UI §12 describes ("each row opens `kang explain`"). No `cost`
field either: M4/M5 are zero-model by construction (no model calls exist
to cost), the same gap this session's `system.health`/Ledger note
already names — not silently invented here as zeros.
"""

from __future__ import annotations

from pydantic import BaseModel

__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "InvocationListItem",
    "InvocationListRequest",
    "InvocationListResponse",
]

DEFAULT_LIMIT = 50
MAX_LIMIT = 500  # 12_API §15's standing limit: "default page 50, max 500" —
#   the handler (operations.py::make_invocation_list_handler) clamps to
#   this same pair, one source of truth for both sides of the contract.


class InvocationListRequest(BaseModel):
    """`invocation.list` params
    (operations.py::make_invocation_list_handler). `limit` is optional;
    an omitted value defaults to 50 and any value above 500 is clamped —
    12_API §15's standing default/max, not a number invented for this
    operation alone."""

    limit: int | None = None


class InvocationListItem(BaseModel):
    """One invocation row for the run-history list — `Invocation`'s
    fields minus `manifest` (see module docstring)."""

    id: str
    correlation_id: str
    kind: str
    operation: str
    principal: str
    trigger: str
    started: str
    finished: str | None
    outcome: str | None


class InvocationListResponse(BaseModel):
    """`invocation.list` result: the `limit` most recent invocations,
    newest-`started`-first — `InvocationStore.recent()`'s contract,
    exposed verbatim. Not cursor-paginated (API-008 names cursor
    pagination as the default for "all list queries") — a named,
    open gap (see `InvocationStore.recent`'s own docstring), not a
    silent omission."""

    invocations: list[InvocationListItem]
