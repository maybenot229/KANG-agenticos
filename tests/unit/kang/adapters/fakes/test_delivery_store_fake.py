"""FakeDeliveryStore against the port contract (13 §2.3 fake/real pairing)."""

from __future__ import annotations

import pytest

from kang.adapters.fakes.delivery_store import FakeDeliveryStore
from tests.fixtures.delivery_store_contract import DeliveryStoreContract


class TestFakeDeliveryStore(DeliveryStoreContract):
    @pytest.fixture
    def store(self, clock) -> FakeDeliveryStore:
        return FakeDeliveryStore(clock)

    # Dead letters (the fake does not model the event FK — 13 §2.3 records
    # this divergence: the sqlite adapter enforces it, tested there).
    def test_record_and_list_dead_letter(self, store):
        store.record_dead_letter("dl-1", 5, "plugin.x", 5, "boom")
        clock_and = store.dead_letters()
        assert [d.id for d in clock_and] == ["dl-1"]
        assert clock_and[0].event_seq == 5

    def test_dead_letters_oldest_first(self, store, clock):
        store.record_dead_letter("dl-1", 1, "s", 5, "e1")
        clock.advance(1)
        store.record_dead_letter("dl-2", 2, "s", 5, "e2")
        assert [d.id for d in store.dead_letters()] == ["dl-1", "dl-2"]
