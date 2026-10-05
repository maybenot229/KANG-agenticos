"""FakeEmbeddingIndex against the shared contract (ADR-055 D6; 13 §2.3)."""

from __future__ import annotations

import pytest

from kang.adapters.fakes.embedding_index import FakeEmbeddingIndex
from kang.adapters.fakes.memory_store import FakeMemoryStore
from kang.domain.ports.embedding_index import EmbeddingVersion
from tests.fixtures.embedding_index_contract import EmbeddingIndexContract


class TestFakeEmbeddingIndex(EmbeddingIndexContract):
    @pytest.fixture
    def memory(self):
        return FakeMemoryStore()

    @pytest.fixture
    def index(self, memory):
        return FakeEmbeddingIndex(memory)

    @pytest.fixture
    def add_version(self, index):
        def add(ver: int, model: str, dim: int, status: str) -> None:
            index.add_version(EmbeddingVersion(ver, model, dim, status))

        return add
