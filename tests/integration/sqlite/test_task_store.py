"""SqliteTaskStore against the port contract + the sqlite-only guarantees:
change capture (07 §5.6), tombstones (07 §5.1), quartet columns (D009).

M0's proof: a trivial entity travels migration → store → test (18 §3 M0).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.migrations import apply_migrations
from kang.adapters.sqlite.task_store import SqliteTaskStore
from kang.domain.tasks import complete_task
from tests.fixtures.task_store_contract import TaskStoreContract

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"


class TestSqliteTaskStore(TaskStoreContract):
    @pytest.fixture
    def conn(self, tmp_path, clock):
        connection = open_connection(tmp_path / "kang.db")
        apply_migrations(connection, MIGRATIONS_DIR, clock)
        yield connection
        connection.close()

    @pytest.fixture
    def store(self, conn, clock) -> SqliteTaskStore:
        return SqliteTaskStore(conn, clock)

    # -- sqlite-only guarantees ------------------------------------------

    def test_task_table_carries_the_quartet_columns(self, conn, store):
        columns = {row[1] for row in conn.execute("PRAGMA table_info(task)")}
        assert {"created_at", "updated_at", "device_id", "revision"} <= columns

    def test_insert_is_change_captured(self, conn, store, clock):
        task = self._new_task(clock)
        store.create(task)
        entity, entity_id, op, fields, revision, device_id, at = conn.execute(
            "SELECT entity, entity_id, op, fields, revision, device_id, at "
            "FROM change_log WHERE op = 'insert'"
        ).fetchone()
        assert (entity, entity_id, op, fields) == ("task", task.id, "insert", None)
        assert (revision, device_id) == (1, task.device_id)
        assert at == clock.now().isoformat()

    def test_update_capture_names_the_changed_fields(self, conn, store, clock):
        task = self._new_task(clock)
        store.create(task)
        clock.advance(60)
        store.update(complete_task(task, clock))
        fields, revision = conn.execute(
            "SELECT fields, revision FROM change_log WHERE op = 'update'"
        ).fetchone()
        assert set(json.loads(fields)) == {"status", "completed_at"}
        assert revision == 2

    def test_delete_is_captured_and_tombstoned(self, conn, store, clock):
        task = self._new_task(clock)
        store.create(task)
        store.delete(task.id, deleted_by="kang")
        op_row = conn.execute(
            "SELECT entity_id, revision FROM change_log WHERE op = 'delete'"
        ).fetchone()
        assert op_row == (task.id, 1)
        tombstone = conn.execute(
            "SELECT id, entity, deleted_by FROM tombstone WHERE id = ?",
            (task.id,),
        ).fetchone()
        assert tombstone == (task.id, "task", "kang")

    def test_capture_log_orders_by_single_writer_seq(self, conn, store, clock):
        task = self._new_task(clock)
        store.create(task)
        clock.advance(1)
        store.update(complete_task(task, clock))
        store.delete(task.id, deleted_by="kang")
        ops = [row[0] for row in conn.execute("SELECT op FROM change_log ORDER BY seq")]
        assert ops == ["insert", "update", "delete"]
