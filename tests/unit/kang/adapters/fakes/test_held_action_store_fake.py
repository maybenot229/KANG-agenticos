"""FakeHeldActionStore against the port contract (13 §2.3)."""

from __future__ import annotations

import pytest

from kang.adapters.fakes.held_action_store import FakeHeldActionStore
from tests.fixtures.held_action_store_contract import HeldActionStoreContract


class TestFakeHeldActionStore(HeldActionStoreContract):
    @pytest.fixture
    def store(self) -> FakeHeldActionStore:
        return FakeHeldActionStore()
