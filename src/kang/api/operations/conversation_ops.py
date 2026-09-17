"""`conversation.purge` handler (ADR-047).

Layer: api.
Constitutional home: 06_MEMORY §7.1 (conversation transcripts, 90d
default), docs/adr/047-conversation-retention-purge.md (this handler's
own design, including why `CONVERSATION_RETENTION_DAYS` is a plain
constant rather than a `memory.toml` read — that file does not exist
yet, Phase 2 hasn't started).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from kang.api.dispatch import Handler, HandlerContext
from kang.domain.ports.clock import Clock
from kang.domain.ports.conversation_store import ConversationStore

__all__ = ["CONVERSATION_RETENTION_DAYS", "make_conversation_purge_handler"]

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
