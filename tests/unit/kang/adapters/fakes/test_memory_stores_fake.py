"""The memory-side fakes against their port contracts (13 §2.3 pairing), plus
the fake unit of work's atomic rollback."""

from __future__ import annotations

import pytest

from kang.adapters.fakes.candidate_queue_store import FakeCandidateQueueStore
from kang.adapters.fakes.memory_store import FakeMemoryStore
from kang.adapters.fakes.unit_of_work import FakeUnitOfWork
from tests.fixtures.candidate_queue_store_contract import (
    CandidateQueueStoreContract,
    candidate,
)
from tests.fixtures.memory_store_contract import MemoryStoreContract, record


class TestFakeMemoryStore(MemoryStoreContract):
    @pytest.fixture
    def store(self):
        return FakeMemoryStore()


class TestFakeCandidateQueueStore(CandidateQueueStoreContract):
    @pytest.fixture
    def store(self):
        return FakeCandidateQueueStore()


def test_the_fake_unit_of_work_rolls_every_participant_back_together():
    memory, queue = FakeMemoryStore(), FakeCandidateQueueStore()
    queue.enqueue(candidate())
    uow = FakeUnitOfWork(memory, queue)

    def work():
        memory.insert_record(record(id="cand-1"))
        queue.resolve("cand-1", "approved", "2026-09-22T10:00:00+00:00")
        raise RuntimeError("crash before commit")

    with pytest.raises(RuntimeError):
        uow.run(work)
    assert memory.get("cand-1") is None
    assert queue.get("cand-1").pending


def test_the_fake_unit_of_work_keeps_the_writes_when_the_work_succeeds():
    memory, queue = FakeMemoryStore(), FakeCandidateQueueStore()
    queue.enqueue(candidate())
    FakeUnitOfWork(memory, queue).run(
        lambda: (
            memory.insert_record(record(id="cand-1")),
            queue.resolve("cand-1", "approved", "2026-09-22T10:00:00+00:00"),
        )
    )
    assert memory.get("cand-1") is not None
    assert queue.get("cand-1").resolved == "approved"
