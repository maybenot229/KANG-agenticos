"""Request/response schemas for `conversation.purge`/`.list` and
`message.list` (ADR-047; `.list` pair added same session, 02_PRODUCT_
REQUIREMENTS.md:697's "Conversation history" system view).

Layer: api.
Constitutional home: 12_API §2, ADR-047 D2, 12_API §15 (default page
50 / max 500 — the same standing limit `invocation.list` already
uses, not a number invented for this pair).
"""

from __future__ import annotations

from pydantic import BaseModel

__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "ConversationListItem",
    "ConversationListRequest",
    "ConversationListResponse",
    "ConversationPurgeRequest",
    "ConversationPurgeResponse",
    "MessageListItem",
    "MessageListRequest",
    "MessageListResponse",
]

DEFAULT_LIMIT = 50
MAX_LIMIT = 500


class ConversationListRequest(BaseModel):
    """`conversation.list` params (operations.py::
    make_conversation_list_handler). `limit` is optional; an omitted
    value defaults to 50 and any value above 500 is clamped, mirroring
    `invocation.list`'s own contract exactly."""

    limit: int | None = None


class ConversationListItem(BaseModel):
    """One conversation row for the history list."""

    id: str
    started: str
    last_message: str
    title: str | None
    message_count: int


class ConversationListResponse(BaseModel):
    """`conversation.list` result: the `limit` most recently active
    conversations, newest-`last_message`-first. Not cursor-paginated
    (API-008 names cursor pagination as the default for "all list
    queries") — the same named, open gap `invocation.list` already
    carries, not a silent omission. Purged conversations are excluded
    — nothing left to read."""

    conversations: list[ConversationListItem]


class MessageListRequest(BaseModel):
    """`message.list` params (operations.py::make_message_list_handler).
    `conversation_id` is required; an unknown one refuses with
    `invalid_request` (`ConversationNotFound`, mirroring `chat.send`'s
    own handling)."""

    conversation_id: str
    limit: int | None = None


class MessageListItem(BaseModel):
    """One message row — `Message`'s fields verbatim."""

    id: str
    role: str
    content: str
    at: str


class MessageListResponse(BaseModel):
    """`message.list` result: the `limit` most recent messages in the
    named conversation, OLDEST first — `ConversationStore.
    recent_messages`'s own contract, exposed verbatim, pure API-layer
    exposure like `deadline.list`/`held_action.list` before it (no new
    domain logic)."""

    messages: list[MessageListItem]


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
