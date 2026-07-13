"""DeliveryStore port-contract suite — the cursor behavior shared by fake
and sqlite (13 §2.3). Subclasses provide ``store`` wired to ``clock``.

Dead-letter recording is NOT in this shared suite: the real dead_letter row
carries a foreign key to event(seq) (§5.2 DDL), so it is only recordable
where the referenced event exists — tested per-implementation (the fake in
its own file, the sqlite adapter with a real seeded event).
"""

from __future__ import annotations

import pytest

from kang.adapters.fakes.clock import FakeClock


class DeliveryStoreContract:
    @pytest.fixture
    def clock(self) -> FakeClock:
        return FakeClock()

    def test_unknown_subscriber_cursor_is_zero(self, store):
        assert store.cursor("agent:planner") == 0

    def test_advance_then_read_cursor(self, store):
        store.advance_cursor("agent:planner", 7)
        assert store.cursor("agent:planner") == 7

    def test_cursors_are_per_subscriber(self, store):
        store.advance_cursor("a", 3)
        store.advance_cursor("b", 9)
        assert store.cursor("a") == 3
        assert store.cursor("b") == 9

    def test_cursor_never_retreats(self, store):
        store.advance_cursor("a", 10)
        store.advance_cursor("a", 4)
        assert store.cursor("a") == 10
