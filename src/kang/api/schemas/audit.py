"""Request/response schemas for `audit.list` (ADR-010 Ruling 1).

Layer: api.
Constitutional home: 09_UI §12 ("Activity: the human-readable audit
stream (S5): time · principal · action · one-line reasoning ·
correlation link. Filterable by principal, action class, date. This
view reads the append-only log; it MUST offer no edit or delete
affordances whatsoever"). Added 2026-08-05 — `AuditService.records()`/
`.months()` already existed as thin pass-throughs over the `AuditLog`
port; this is their first API-layer exposure.

No delete/edit path exists anywhere in this schema pair, matching
09_UI §12's own rule about the Activity view's shape.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

__all__ = [
    "AuditListRequest",
    "AuditListResponse",
    "AuditRecordItem",
]


class AuditListRequest(BaseModel):
    """`audit.list` params (operations.py::make_audit_list_handler).
    `month` is optional ('YYYY-MM'); an omitted value defaults to the
    injected clock's current month, mirroring `plan.generate`'s own
    `plan_date` default-to-today convention."""

    month: str | None = None


class AuditRecordItem(BaseModel):
    """One audit record — `AuditEntry`'s fields, unfiltered (`domain/
    ports/audit.py`). No `entry_hash`/`prev_hash`: SEC-013's chain
    verification is a `kang explain`/ops concern (`tools/`, not built
    yet), not this screen's — Activity renders the human-readable
    stream, not the tamper-evidence machinery underneath it."""

    at: str
    principal: str
    action: str
    correlation_id: str | None
    details: dict[str, Any] | None = None


class AuditListResponse(BaseModel):
    """`audit.list` result: every record of the requested month, oldest
    first — `AuditLog.records()`'s existing contract, exposed verbatim.
    Filtering by principal/action-class/date (09_UI §12) happens at the
    UI layer against one month's records; this operation does no
    filtering of its own."""

    month: str
    records: list[AuditRecordItem]
