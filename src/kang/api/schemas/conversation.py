"""Request/response schema for `conversation.purge` (ADR-047).

Layer: api.
Constitutional home: 12_API §2, ADR-047 D2.
"""

from __future__ import annotations

from pydantic import BaseModel

__all__ = ["ConversationPurgeRequest", "ConversationPurgeResponse"]


class ConversationPurgeRequest(BaseModel):
    """`conversation.purge` params (operations.py::
    make_conversation_purge_handler). The handler ignores `params`
    entirely — no fields to accept, mirroring `deadline.sweep`'s own
    empty request."""


class ConversationPurgeResponse(BaseModel):
    """`conversation.purge` result. `count` is legitimately zero on
    most runs (nothing yet past the retention threshold) — a normal
    outcome, not a failure signal (ADR-047 Consequences)."""

    purged: list[str]
    count: int
