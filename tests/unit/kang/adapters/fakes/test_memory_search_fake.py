"""FakeMemorySearchStore against the shared contract (ADR-056 D1)."""

from __future__ import annotations

import pytest

from kang.adapters.fakes.memory_search import FakeMemorySearchStore
from kang.adapters.fakes.memory_store import FakeMemoryStore
from tests.fixtures.memory_search_contract import MemorySearchStoreContract


class TestFakeMemorySearchStore(MemorySearchStoreContract):
    @pytest.fixture
    def memory(self):
        return FakeMemoryStore()

    @pytest.fixture
    def search(self, memory):
        return FakeMemorySearchStore(memory)
