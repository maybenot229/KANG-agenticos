"""FakeTaskStore against the port contract (13 §2.3 fake/real pairing)."""

from __future__ import annotations

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.task_store import FakeTaskStore
from tests.fixtures.task_store_contract import TaskStoreContract


class TestFakeTaskStore(TaskStoreContract):
    @pytest.fixture
    def store(self, clock: FakeClock) -> FakeTaskStore:
        return FakeTaskStore(clock)

    def test_delete_records_a_tombstone(self, store, clock):
        task = self._new_task(clock)
        store.create(task)
        store.delete(task.id, deleted_by="kang")
        assert store.tombstones == [(task.id, "task", "kang")]
