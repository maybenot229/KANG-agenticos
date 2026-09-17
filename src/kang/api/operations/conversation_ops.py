"""`conversation.purge`/`.list` and `message.list` handlers (ADR-047;
the `.list` pair, 02_PRODUCT_REQUIREMENTS.md:697's "Conversation
history" system view).

Layer: api.
Constitutional home: 06_MEMORY §7.1 (conversation transcripts, 90d
default), docs/adr/047-conversation-retention-purge.md (`purge`'s own
design, including why `CONVERSATION_RETENTION_DAYS` is a plain
constant rather than a `memory.toml` read — that file does not exist
yet, Phase 2 hasn't started), 12_API §8/§15 (the `.list` pair: plain
mechanical query-operation additions, no ADR triggered — the same
"pure API-layer exposure" shape `deadline.list`/`invocation.list`
already established, not a new pattern).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from kang.api.dispatch import Handler, HandlerContext
from kang.api.errors import ApiError
from kang.api.schemas.conversation import DEFAULT_LIMIT, MAX_LIMIT
from kang.domain.ports.clock import Clock
from kang.domain.ports.conversation_store import ConversationStore

__all__ = [
    "CONVERSATION_RETENTION_DAYS",
    "make_conversation_list_handler",
    "make_conversation_purge_handler",
    "make_message_list_handler",
]


def _clamp_limit(requested: int | None) -> int:
    # max(1, ...): SQLite's LIMIT -1/0 means "unlimited" — clamping only
    # the top end would let a non-positive `limit` defeat the entire
    # point of a bounded page (same reasoning `invocation.list` uses).
    return DEFAULT_LIMIT if requested is None else max(1, min(requested, MAX_LIMIT))


# 06_MEMORY §7.1 / Appendix A's own documented default (`[retention]
# conversation_days = 90`). Not read from `memory.toml` — that file
# isn't real yet — the same honest-hardcode shape `scheduler_wiring.py`'s
# `TICK_INTERVAL_S` already uses. Becomes `memory.toml`'s first real
# consumer once Phase 2 builds it; not solved here (ADR-047 D2).
CONVERSATION_RETENTION_DAYS = 90


def make_conversation_purge_handler(
    conversations: ConversationStore, clock: Clock
) -> Handler:
    """ADR-047: purge every conversation whose transcript is older than
    `CONVERSATION_RETENTION_DAYS`. Unconditional this slice — 06_MEMORY
    §7.1's "explicit saves extracted first" qualifier has no mechanism
    to hang off yet (that's `from_conversation` extraction, Phase 2)."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        cutoff = (clock.now() - timedelta(days=CONVERSATION_RETENTION_DAYS)).isoformat()
        purged = conversations.purge_stale(cutoff)
        return {"purged": list(purged), "count": len(purged)}

    return handler


def make_conversation_list_handler(conversations: ConversationStore) -> Handler:
    """`conversation.list`: the `limit` most recently active
    conversations, newest first — pure exposure of `ConversationStore.
    list_recent`, no new domain logic."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        limit = _clamp_limit(params.get("limit"))
        return {
            "conversations": [
                {
                    "id": c.id,
                    "started": c.started,
                    "last_message": c.last_message,
                    "title": c.title,
                    "message_count": c.message_count,
                }
                for c in conversations.list_recent(limit)
            ]
        }

    return handler


def make_message_list_handler(conversations: ConversationStore) -> Handler:
    """`message.list`: the `limit` most recent messages in one named
    conversation, oldest first — pure exposure of `ConversationStore.
    recent_messages`. An unknown `conversation_id` refuses with
    `invalid_request`, mirroring `chat.send`'s own handling."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        conversation_id = params["conversation_id"]
        # recent_messages() does not raise on an unknown id (its own
        # documented contract — empty tuple for "unknown or empty"
        # alike) — get() first is how this handler tells the two apart.
        if conversations.get(conversation_id) is None:
            raise ApiError(
                "invalid_request", f"no such conversation {conversation_id!r}"
            )
        limit = _clamp_limit(params.get("limit"))
        messages = conversations.recent_messages(conversation_id, limit)
        return {
            "messages": [
                {"id": m.id, "role": m.role, "content": m.content, "at": m.at}
                for m in messages
            ]
        }

    return handler
