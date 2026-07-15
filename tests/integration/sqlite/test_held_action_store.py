"""SqliteHeldActionStore against the port contract + durability across reopen."""

from __future__ import annotations

from pathlib import Path

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.held_action_store import SqliteHeldActionStore
from kang.adapters.sqlite.migrations import apply_migrations
from tests.fixtures.held_action_store_contract import HeldActionStoreContract, _held

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"


class TestSqliteHeldActionStore(HeldActionStoreContract):
    @pytest.fixture
    def conn(self, tmp_path):
        connection = open_connection(tmp_path / "kang.db")
        apply_migrations(connection, MIGRATIONS_DIR, FakeClock())
        yield connection
        connection.close()

    @pytest.fixture
    def store(self, conn) -> SqliteHeldActionStore:
        return SqliteHeldActionStore(conn)

    def test_pending_survives_reopen(self, tmp_path):
        first = open_connection(tmp_path / "kang.db")
        apply_migrations(first, MIGRATIONS_DIR, FakeClock())
        SqliteHeldActionStore(first).create(_held(0))
        first.close()
        second = open_connection(tmp_path / "kang.db")
        assert [h.id for h in SqliteHeldActionStore(second).pending()] == ["held-0000"]
        second.close()

    def test_status_check_constraint_is_enforced(self, conn, store):
        import sqlite3

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO held_action (id, action, principal, reason, "
                "reversibility, correlation_id, created_at, expires_at, status) "
                "VALUES ('h', 'a', 'p', 'r', 'rev', 'c', 't', 't', 'bogus')"
            )
