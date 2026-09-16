"""SqliteConversationStore — chat transcript persistence (ADR-046,
07_DATABASE §5.5) — against the real, migrated kang.db."""

from __future__ import annotations

from pathlib import Path

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.conversation_store import SqliteConversationStore
from kang.adapters.sqlite.migrations import apply_migrations
from tests.fixtures.conversation_store_contract import ConversationStoreContract

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"


@pytest.fixture
def conn(tmp_path):
    connection = open_connection(tmp_path / "kang.db")
    apply_migrations(connection, MIGRATIONS_DIR, FakeClock())
    yield connection
    connection.close()


class TestSqliteConversationStore(ConversationStoreContract):
    @pytest.fixture
    def store(self, conn) -> SqliteConversationStore:
        return SqliteConversationStore(conn)

    def test_messages_survive_a_reopen(self, tmp_path, conn):
        store = SqliteConversationStore(conn)
        store.start("conv-1", "2026-09-16T10:00:00Z")
        store.append_message("conv-1", "msg-1", "kang", "hi", "2026-09-16T10:01:00Z")
        conn.close()

        reopened = open_connection(tmp_path / "kang.db")
        try:
            reopened_store = SqliteConversationStore(reopened)
            conversation = reopened_store.get("conv-1")
            assert conversation is not None
            assert conversation.message_count == 1
            messages = reopened_store.recent_messages("conv-1", 20)
            assert [m.content for m in messages] == ["hi"]
        finally:
            reopened.close()

    def test_deleting_a_conversation_cascades_to_its_messages(self, conn):
        store = SqliteConversationStore(conn)
        store.start("conv-1", "2026-09-16T10:00:00Z")
        store.append_message("conv-1", "msg-1", "kang", "hi", "2026-09-16T10:01:00Z")

        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM conversation WHERE id = ?", ("conv-1",))
        conn.execute("COMMIT")

        remaining = conn.execute(
            "SELECT COUNT(*) FROM message WHERE conversation_id = ?", ("conv-1",)
        ).fetchone()[0]
        assert remaining == 0  # ON DELETE CASCADE, 07_DATABASE.md:537
