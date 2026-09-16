"""ConversationStore port-contract suite — run identically against the
fake and the real adapter (13 §2.3: divergence between fake and real is
itself a red build).

Subclasses provide a `store` fixture (a fresh `ConversationStore`).
"""

from __future__ import annotations

import pytest

from kang.domain.ports.conversation_store import Conversation, ConversationNotFound

_T0 = "2026-09-16T10:00:00Z"
_T1 = "2026-09-16T10:01:00Z"
_T2 = "2026-09-16T10:01:05Z"
_T3 = "2026-09-16T10:01:10Z"


class ConversationStoreContract:
    def test_start_creates_an_empty_conversation(self, store):
        conversation = store.start("conv-1", _T0)
        assert conversation == Conversation(
            id="conv-1",
            started=_T0,
            last_message=_T0,
            title=None,
            message_count=0,
            purged=False,
        )

    def test_get_returns_the_started_conversation(self, store):
        store.start("conv-1", _T0)
        assert store.get("conv-1").id == "conv-1"

    def test_get_returns_none_for_an_unknown_conversation(self, store):
        assert store.get("never-started") is None

    def test_append_message_raises_for_an_unknown_conversation(self, store):
        with pytest.raises(ConversationNotFound):
            store.append_message("never-started", "msg-1", "kang", "hi", _T0)

    def test_append_message_bumps_count_and_last_message(self, store):
        store.start("conv-1", _T0)
        store.append_message("conv-1", "msg-1", "kang", "hi", _T1)
        conversation = store.get("conv-1")
        assert conversation.message_count == 1
        assert conversation.last_message == _T1

        store.append_message("conv-1", "msg-2", "agent", "hello back", _T2)
        conversation = store.get("conv-1")
        assert conversation.message_count == 2
        assert conversation.last_message == _T2

    def test_recent_messages_returns_oldest_first(self, store):
        store.start("conv-1", _T0)
        store.append_message("conv-1", "msg-1", "kang", "first", _T1)
        store.append_message("conv-1", "msg-2", "agent", "second", _T2)
        store.append_message("conv-1", "msg-3", "kang", "third", _T3)

        messages = store.recent_messages("conv-1", limit=20)
        assert [m.content for m in messages] == ["first", "second", "third"]

    def test_recent_messages_respects_the_limit_keeping_the_newest(self, store):
        store.start("conv-1", _T0)
        for i in range(5):
            store.append_message(
                "conv-1", f"msg-{i}", "kang", f"turn {i}", f"2026-09-16T10:0{i}:00Z"
            )
        messages = store.recent_messages("conv-1", limit=2)
        assert [m.content for m in messages] == ["turn 3", "turn 4"]

    def test_recent_messages_is_empty_for_an_unknown_conversation(self, store):
        assert store.recent_messages("never-started", limit=20) == ()

    def test_two_conversations_keep_independent_transcripts(self, store):
        store.start("conv-1", _T0)
        store.start("conv-2", _T0)
        store.append_message("conv-1", "msg-1", "kang", "for conv-1", _T1)

        conv1_messages = store.recent_messages("conv-1", limit=20)
        assert [m.content for m in conv1_messages] == ["for conv-1"]
        assert store.recent_messages("conv-2", limit=20) == ()
