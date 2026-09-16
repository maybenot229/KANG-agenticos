"""FakeConversationStore against the port contract (13 §2.3 fake/real pairing)."""

from __future__ import annotations

import pytest

from kang.adapters.fakes.conversation_store import FakeConversationStore
from tests.fixtures.conversation_store_contract import ConversationStoreContract


class TestFakeConversationStore(ConversationStoreContract):
    @pytest.fixture
    def store(self):
        return FakeConversationStore()
