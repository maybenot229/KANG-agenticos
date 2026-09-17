"""`conversation.purge` handler tests (ADR-047).

Claim: every conversation whose transcript is older than
`CONVERSATION_RETENTION_DAYS` gets purged (messages deleted,
`conversation.purged` set), unconditionally this slice, and nothing
younger is touched.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.conversation_store import FakeConversationStore
from kang.api.dispatch import HandlerContext
from kang.api.operations.conversation_ops import (
    CONVERSATION_RETENTION_DAYS,
    make_conversation_purge_handler,
)

CONTEXT = HandlerContext(
    principal="agent:memory_steward",
    correlation_id="corr-1",
    trigger="scheduler",
    first_party=False,
)


def test_purges_a_conversation_older_than_the_retention_window():
    conversations = FakeConversationStore()
    started = "2026-01-01T00:00:00+00:00"
    conversations.start("conv-old", started)
    conversations.append_message("conv-old", "msg-1", "kang", "old", started)
    clock = FakeClock(
        start=datetime(2026, 1, 1, tzinfo=timezone.utc)
        + timedelta(days=CONVERSATION_RETENTION_DAYS + 1)
    )
    handler = make_conversation_purge_handler(conversations, clock)

    result = handler(CONTEXT, {})

    assert result == {"purged": ["conv-old"], "count": 1}
    assert conversations.get("conv-old").purged is True
    assert conversations.recent_messages("conv-old", limit=20) == ()


def test_leaves_a_conversation_inside_the_retention_window():
    conversations = FakeConversationStore()
    started = "2026-01-01T00:00:00+00:00"
    conversations.start("conv-recent", started)
    conversations.append_message("conv-recent", "msg-1", "kang", "recent", started)
    clock = FakeClock(start=datetime(2026, 1, 2, tzinfo=timezone.utc))
    handler = make_conversation_purge_handler(conversations, clock)

    result = handler(CONTEXT, {})

    assert result == {"purged": [], "count": 0}
    assert conversations.get("conv-recent").purged is False


def test_a_normal_night_with_nothing_to_purge_returns_zero_not_an_error():
    conversations = FakeConversationStore()
    clock = FakeClock()
    handler = make_conversation_purge_handler(conversations, clock)

    assert handler(CONTEXT, {}) == {"purged": [], "count": 0}
