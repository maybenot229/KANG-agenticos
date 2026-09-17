"""`conversation.purge`/`.list` and `message.list` handler tests
(ADR-047).

Claims: every conversation whose transcript is older than
`CONVERSATION_RETENTION_DAYS` gets purged (messages deleted,
`conversation.purged` set), unconditionally this slice, and nothing
younger is touched. `conversation.list`/`message.list` are pure
exposure of the store's own `list_recent`/`recent_messages` — no new
domain logic, including an unknown `conversation_id` refusing with
`invalid_request`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.conversation_store import FakeConversationStore
from kang.api.dispatch import HandlerContext
from kang.api.errors import ApiError
from kang.api.operations.conversation_ops import (
    CONVERSATION_RETENTION_DAYS,
    make_conversation_list_handler,
    make_conversation_purge_handler,
    make_message_list_handler,
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


def test_conversation_list_exposes_the_store_newest_first():
    conversations = FakeConversationStore()
    conversations.start("conv-1", "2026-01-01T00:00:00+00:00")
    conversations.start("conv-2", "2026-01-02T00:00:00+00:00")
    handler = make_conversation_list_handler(conversations)

    result = handler(CONTEXT, {})

    assert [c["id"] for c in result["conversations"]] == ["conv-2", "conv-1"]


def test_conversation_list_clamps_an_over_large_limit():
    conversations = FakeConversationStore()
    for i in range(3):
        conversations.start(f"conv-{i}", f"2026-01-0{i + 1}T00:00:00+00:00")
    handler = make_conversation_list_handler(conversations)

    result = handler(CONTEXT, {"limit": 999999})

    assert len(result["conversations"]) == 3


def test_message_list_exposes_the_store_oldest_first():
    conversations = FakeConversationStore()
    conversations.start("conv-1", "2026-01-01T00:00:00+00:00")
    conversations.append_message(
        "conv-1", "msg-1", "kang", "first", "2026-01-01T00:01:00+00:00"
    )
    conversations.append_message(
        "conv-1", "msg-2", "agent", "second", "2026-01-01T00:02:00+00:00"
    )
    handler = make_message_list_handler(conversations)

    result = handler(CONTEXT, {"conversation_id": "conv-1"})

    assert [m["content"] for m in result["messages"]] == ["first", "second"]


def test_message_list_refuses_an_unknown_conversation_id():
    conversations = FakeConversationStore()
    handler = make_message_list_handler(conversations)

    with pytest.raises(ApiError) as excinfo:
        handler(CONTEXT, {"conversation_id": "never-started"})

    assert excinfo.value.code == "invalid_request"
