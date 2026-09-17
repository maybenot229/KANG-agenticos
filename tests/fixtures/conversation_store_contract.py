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

    def test_list_recent_orders_newest_last_message_first(self, store):
        store.start("conv-1", _T0)
        store.start("conv-2", _T0)
        store.append_message("conv-1", "msg-1", "kang", "first", _T1)
        store.append_message("conv-2", "msg-2", "kang", "second", _T2)

        listed = store.list_recent(limit=20)

        assert [c.id for c in listed] == ["conv-2", "conv-1"]

    def test_list_recent_respects_the_limit(self, store):
        for i in range(5):
            store.start(f"conv-{i}", f"2026-09-16T10:0{i}:00Z")

        listed = store.list_recent(limit=2)

        assert len(listed) == 2

    def test_list_recent_excludes_purged_conversations(self, store):
        store.start("conv-1", _T0)
        store.append_message("conv-1", "msg-1", "kang", "old", _T1)
        store.purge_stale(cutoff="2026-12-01T00:00:00Z")

        assert store.list_recent(limit=20) == ()

    def test_purge_stale_deletes_messages_but_keeps_the_conversation_id(self, store):
        store.start("conv-1", _T0)
        store.append_message("conv-1", "msg-1", "kang", "old", _T1)

        purged = store.purge_stale(cutoff="2026-12-01T00:00:00Z")

        assert purged == ("conv-1",)
        conversation = store.get("conv-1")
        assert conversation.id == "conv-1"
        assert conversation.purged is True
        assert store.recent_messages("conv-1", limit=20) == ()

    def test_purge_stale_leaves_conversations_at_or_after_the_cutoff(self, store):
        store.start("conv-1", _T0)
        store.append_message("conv-1", "msg-1", "kang", "recent", _T1)

        purged = store.purge_stale(cutoff="2020-01-01T00:00:00Z")

        assert purged == ()
        conversation = store.get("conv-1")
        assert conversation.purged is False
        assert [m.content for m in store.recent_messages("conv-1", limit=20)] == [
            "recent"
        ]

    def test_purge_stale_is_idempotent_on_an_already_purged_conversation(self, store):
        store.start("conv-1", _T0)
        store.append_message("conv-1", "msg-1", "kang", "old", _T1)
        first = store.purge_stale(cutoff="2026-12-01T00:00:00Z")
        second = store.purge_stale(cutoff="2026-12-01T00:00:00Z")

        assert first == ("conv-1",)
        assert second == ()
