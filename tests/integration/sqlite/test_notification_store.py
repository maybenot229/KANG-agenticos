"""SqliteNotificationStore against the port contract + schema guarantees."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.migrations import apply_migrations
from kang.adapters.sqlite.notification_store import SqliteNotificationStore
from tests.fixtures.notification_store_contract import (
    NotificationStoreContract,
    _notification,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"


class TestSqliteNotificationStore(NotificationStoreContract):
    @pytest.fixture
    def conn(self, tmp_path):
        connection = open_connection(tmp_path / "kang.db")
        apply_migrations(connection, MIGRATIONS_DIR, FakeClock())
        yield connection
        connection.close()

    @pytest.fixture
    def store(self, conn) -> SqliteNotificationStore:
        return SqliteNotificationStore(conn)

    def test_survives_reopen(self, tmp_path):
        first = open_connection(tmp_path / "kang.db")
        apply_migrations(first, MIGRATIONS_DIR, FakeClock())
        SqliteNotificationStore(first).create(_notification(0))
        first.close()
        second = open_connection(tmp_path / "kang.db")
        assert [n.id for n in SqliteNotificationStore(second).queued()] == ["ntf-0000"]
        second.close()

    def test_priority_check_constraint_is_enforced(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO notification (id, priority, principal, "
                "correlation_id, entity_refs, payload, state, created_at) "
                "VALUES ('n', 'urgent', 'p', 'c', '[]', '{}', 'queued', 't')"
            )

    def test_state_check_constraint_is_enforced(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO notification (id, priority, principal, "
                "correlation_id, entity_refs, payload, state, created_at) "
                "VALUES ('n', 'critical', 'p', 'c', '[]', '{}', 'sent', 't')"
            )

    def test_notification_carries_no_sync_quartet(self, conn):
        """ADR-005: per-device operational state, like held_action and
        invocation — no device_id/revision, deliberately."""
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(notification)").fetchall()
        }
        assert "device_id" not in columns
        assert "revision" not in columns
