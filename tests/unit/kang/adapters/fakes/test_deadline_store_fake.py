"""FakeDeadlineStore against the same port contract as the real store."""

from __future__ import annotations

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.deadline_store import FakeDeadlineStore
from tests.fixtures.deadline_store_contract import DeadlineStoreContract


class TestFakeDeadlineStore(DeadlineStoreContract):
    @pytest.fixture
    def store(self) -> FakeDeadlineStore:
        return FakeDeadlineStore(FakeClock())
