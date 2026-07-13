"""SqliteDeliveryStore against the port contract + durability across reopen."""

from __future__ import annotations

import pytest

from kang.adapters.eventlog.delivery_store import SqliteDeliveryStore
from kang.adapters.eventlog.event_log import SqliteEventLog
from kang.adapters.eventlog.schema import open_eventlog
from tests.fixtures.delivery_store_contract import DeliveryStoreContract
from tests.fixtures.event_log_contract import make_envelope


class TestSqliteDeliveryStore(DeliveryStoreContract):
    @pytest.fixture
    def conn(self, tmp_path):
        connection = open_eventlog(tmp_path / "eventlog.db")
        yield connection
        connection.close()

    @pytest.fixture
    def store(self, conn, clock) -> SqliteDeliveryStore:
        return SqliteDeliveryStore(conn, clock)

    def test_cursor_survives_reopen(self, tmp_path, clock):
        first = open_eventlog(tmp_path / "eventlog.db")
        SqliteDeliveryStore(first, clock).advance_cursor("agent:planner", 12)
        first.close()
        second = open_eventlog(tmp_path / "eventlog.db")
        assert SqliteDeliveryStore(second, clock).cursor("agent:planner") == 12
        second.close()

    # Dead letters carry a FK to event(seq) (§5.2) — the event must exist.
    def test_record_dead_letter_references_a_real_event(self, conn, store, clock):
        event_log = SqliteEventLog(conn, clock)
        seq = event_log.append(make_envelope(0))
        dead = store.record_dead_letter("dl-1", seq, "plugin.x", 5, "boom")
        assert dead.event_seq == seq
        assert [d.id for d in store.dead_letters()] == ["dl-1"]

    def test_dead_letter_for_absent_event_is_rejected(self, store):
        import sqlite3

        with pytest.raises(sqlite3.IntegrityError):
            store.record_dead_letter("dl-x", 999, "s", 5, "no such event")
