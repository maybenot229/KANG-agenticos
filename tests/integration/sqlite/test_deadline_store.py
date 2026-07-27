"""SqliteDeadlineStore against the port contract + schema-level guarantees."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.deadline_store import SqliteDeadlineStore
from kang.adapters.sqlite.migrations import apply_migrations
from tests.fixtures.deadline_store_contract import DeadlineStoreContract, _deadline

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"


class TestSqliteDeadlineStore(DeadlineStoreContract):
    @pytest.fixture
    def conn(self, tmp_path):
        connection = open_connection(tmp_path / "kang.db")
        apply_migrations(connection, MIGRATIONS_DIR, FakeClock())
        yield connection
        connection.close()

    @pytest.fixture
    def store(self, conn) -> SqliteDeadlineStore:
        return SqliteDeadlineStore(conn, FakeClock())

    def test_survives_reopen(self, tmp_path):
        first = open_connection(tmp_path / "kang.db")
        apply_migrations(first, MIGRATIONS_DIR, FakeClock())
        SqliteDeadlineStore(first, FakeClock()).create(_deadline(0))
        first.close()
        second = open_connection(tmp_path / "kang.db")
        assert [d.id for d in SqliteDeadlineStore(second, FakeClock()).active()] == [
            "dl-0000"
        ]
        second.close()

    def test_status_check_constraint_is_enforced(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO deadline (id, kind, title, at, status, created_at, "
                "updated_at, device_id, revision) VALUES "
                "('d', 'custom', 't', 'at', 'bogus', 'c', 'u', 'dev', 1)"
            )

    def test_kind_check_constraint_is_enforced(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO deadline (id, kind, title, at, status, created_at, "
                "updated_at, device_id, revision) VALUES "
                "('d', 'bogus', 't', 'at', 'tracked', 'c', 'u', 'dev', 1)"
            )

    def test_anchor_check_constraint_is_enforced(self, conn):
        # 07 §5.2's table CHECK: a non-self-standing kind must reference a
        # competition or a project.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO deadline (id, kind, title, at, status, created_at, "
                "updated_at, device_id, revision) VALUES "
                "('d', 'submission', 't', 'at', 'tracked', 'c', 'u', 'dev', 1)"
            )

    def test_create_writes_a_change_log_row(self, conn, store):
        store.create(_deadline(0))
        captured = conn.execute(
            "SELECT entity, entity_id, op FROM change_log WHERE entity = 'deadline'"
        ).fetchall()
        assert captured == [("deadline", "dl-0000", "insert")]

    def test_delete_writes_a_tombstone(self, conn, store):
        store.create(_deadline(0))
        store.delete("dl-0000", deleted_by="kang")
        rows = conn.execute(
            "SELECT entity, deleted_by FROM tombstone WHERE id = 'dl-0000'"
        ).fetchall()
        assert rows == [("deadline", "kang")]
