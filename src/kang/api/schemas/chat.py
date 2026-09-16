"""Request/response schemas for `chat.send` (ADR-010 Ruling 1, ADR-044,
ADR-046).

Layer: api.
Constitutional home: 12_API §2, ADR-044 D3, ADR-046 D4. `message`
mirrors `deadline.create`'s own "non-empty after stripping" convention;
`context_chips` is exactly 09_UI_DESIGN.md:89's own "removable chips"
contract, arriving verbatim from the client — nothing here re-derives
context server-side (ADR-044 D4). `conversation_id` omitted starts a
new conversation (the server mints one, matching every other entity
in this codebase); present must name an existing one (ADR-046 D4).
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator

__all__ = ["ChatSendRequest", "ChatSendResponse"]


class ChatSendRequest(BaseModel):
    """`chat.send` params (operations.py::make_chat_send_handler)."""

    message: str = ""
    context_chips: list[str] = []
    conversation_id: str | None = None

    @field_validator("message")
    @classmethod
    def _message_not_blank_after_strip(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must be non-empty")
        return value


class ChatSendResponse(BaseModel):
    """`chat.send` result. `degraded=True` means `reply` is the chat
    agent's own declared degradation text (AGP-8), never an invented
    conversational reply — surfaced explicitly rather than left for the
    client to guess from prose alone (ADR-044 D2). `conversation_id` is
    always present — either freshly minted or the caller's own, echoed
    back (ADR-046 D4); the client passes it on the next call to
    continue this same conversation."""

    reply: str
    degraded: bool
    conversation_id: str
