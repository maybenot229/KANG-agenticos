"""ConversationStore port — chat transcript persistence (ADR-046).

Layer: domain/ports. Ports own their datatypes (17 §7).
Constitutional home: 07_DATABASE §5.5 (`docs/07_DATABASE.md:530-540`, the
`conversation`/`message` schema this port implements), 06_MEMORY §1.3
("Conversation transcripts | History (queryable, but untrusted raw
material) | Conversation store, retention-limited" — explicitly NOT
memory, so nothing here touches the write gate), docs/adr/046-chat-
conversation-history.md (this port's own design).

`conversation`/`message` use UUIDv7 TEXT identity like every other
entity (stable cross-reference for 06_MEMORY §9.1's own future
`from_conversation` link, which must survive transcript purge as an
id-only reference) but are explicitly exempt from the sync quartet
(`device_id`/`revision`) — single-writer, append-only, retention-purged,
not a conflict-resolution candidate (ADR-046's own dated finding,
mirrored in `07_DATABASE.md` and `migrations/0019_conversation.sql`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

__all__ = [
    "MESSAGE_ROLES",
    "Conversation",
    "ConversationNotFound",
    "ConversationStore",
    "Message",
]

# The schema's own closed enum (07_DATABASE.md:538). "kang" = Kang's own
# words; "agent" = a genuine model-generated reply; "kang_system" = a
# real system notice (e.g. a degraded reply's own text, ADR-046 D3) —
# never the agent "speaking," never hidden from the transcript either.
MESSAGE_ROLES = ("kang", "kang_system", "agent")


class ConversationNotFound(Exception):
    """A caller named an existing `conversation_id` that does not exist.
    Distinct from omitting one (which starts a new conversation) —
    naming one that isn't real is a client error, not a create-under-
    that-id request (ADR-046 D4: the server always mints ids for
    creation, matching every other entity in this codebase)."""


@dataclass(frozen=True)
class Conversation:
    """One conversation's own metadata row (07_DATABASE.md:530)."""

    id: str
    started: str  # ISO-8601 — when this conversation began
    last_message: str  # ISO-8601 — timestamp of its most recent message
    title: str | None
    message_count: int
    purged: bool


@dataclass(frozen=True)
class Message:
    """One message row (07_DATABASE.md:535) — immutable once written."""

    id: str
    conversation_id: str
    role: str  # one of MESSAGE_ROLES
    content: str
    at: str  # ISO-8601


class ConversationStore(Protocol):
    """Chat transcript persistence — a plain structured store, not
    memory (06_MEMORY §1.3), so nothing here goes through the write
    gate. `append_message` updates the parent conversation's own
    `message_count`/`last_message` as part of the same write, never a
    separate caller-driven step."""

    def start(self, conversation_id: str, started_at: str) -> Conversation:
        """Create a new, empty conversation. Raises nothing on a
        duplicate id — that would be a wiring defect (a freshly minted
        id colliding), not a runtime condition to handle gracefully."""
        ...

    def get(self, conversation_id: str) -> Conversation | None:
        """`None` if no such conversation exists — the caller's own
        `ConversationNotFound` decision, not this port's."""
        ...

    def append_message(
        self, conversation_id: str, message_id: str, role: str, content: str, at: str
    ) -> Message:
        """Append one message, bump the parent's `message_count` and
        `last_message`, in one write. Raises `ConversationNotFound` if
        `conversation_id` does not exist."""
        ...

    def recent_messages(self, conversation_id: str, limit: int) -> tuple[Message, ...]:
        """The most recent `limit` messages, OLDEST first (ready to
        format straight into a prompt as a transcript) — never newest
        first, which would read backwards. Empty tuple for an unknown
        or empty conversation; this port does not raise on that case,
        callers that care about existence use `get` first."""
        ...
