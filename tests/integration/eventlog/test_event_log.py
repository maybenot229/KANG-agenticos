"""SqliteEventLog against the port contract + the file-level guarantees:
the exact 15 §5.2 DDL, synchronous=FULL own connection (EB-003's redo duty),
pending-window survival across reopen.
"""

from __future__ import annotations

import pytest

from kang.adapters.eventlog.event_log import SqliteEventLog
from kang.adapters.eventlog.schema import open_eventlog
from tests.fixtures.event_log_contract import EventLogContract, make_envelope


class TestSqliteEventLog(EventLogContract):
    @pytest.fixture
    def conn(self, tmp_path):
        connection = open_eventlog(tmp_path / "eventlog.db")
        yield connection
        connection.close()

    @pytest.fixture
    def log(self, conn, clock) -> SqliteEventLog:
        return SqliteEventLog(conn, clock)

    # -- 15 §5.2 DDL, exact ------------------------------------------------

    def test_tables_match_the_five_two_ddl(self, conn, log):
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"event", "subscription_cursor", "dead_letter"} <= tables

    def test_event_columns_match_the_envelope_plus_log_fields(self, conn, log):
        columns = [row[1] for row in conn.execute("PRAGMA table_info(event)")]
        assert columns == [
            "seq",
            "event_id",
            "type",
            "type_version",
            "occurred_at",
            "recorded_at",
            "principal",
            "correlation_id",
            "causation_id",
            "entity_refs",
            "payload",
            "provenance",
            "recovery_grade",
            "device_id",
            "state",
        ]

    def test_the_three_cited_indexes_exist(self, conn, log):
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' "
                "AND name LIKE 'idx_%'"
            )
        }
        assert {"idx_event_type", "idx_event_corr", "idx_event_pending"} <= indexes

    def test_connection_runs_synchronous_full(self, conn, log):
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL

    def test_event_id_uniqueness_is_schema_enforced(self, conn, log):
        import sqlite3

        log.append(make_envelope(0))
        with pytest.raises(sqlite3.IntegrityError):
            log.append(make_envelope(0))  # same event_id

    def test_pending_window_survives_reopen(self, tmp_path, clock):
        first = open_eventlog(tmp_path / "eventlog.db")
        SqliteEventLog(first, clock).append(make_envelope(0))
        first.close()
        second = open_eventlog(tmp_path / "eventlog.db")
        reopened = SqliteEventLog(second, clock)
        assert [event.seq for event in reopened.pending()] == [1]
        second.close()
