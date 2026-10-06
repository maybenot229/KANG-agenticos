"""SqliteMemorySearchStore against the real schema (ADR-056 D1): the shared
contract, plus what only FTS5 shows — stemming, and Kang's text never being
parsed as FTS syntax."""

from __future__ import annotations

from pathlib import Path

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.memory_search import SqliteMemorySearchStore, fts_query
from kang.adapters.sqlite.memory_store import SqliteMemoryStore
from kang.adapters.sqlite.migrations import apply_migrations
from tests.fixtures.memory_search_contract import LIVE, MemorySearchStoreContract
from tests.fixtures.memory_store_contract import record

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"


@pytest.fixture
def conn(tmp_path):
    connection = open_connection(tmp_path / "kang.db")
    apply_migrations(connection, MIGRATIONS_DIR, FakeClock())
    yield connection
    connection.close()


class TestSqliteMemorySearchStore(MemorySearchStoreContract):
    @pytest.fixture
    def memory(self, conn):
        return SqliteMemoryStore(conn)

    @pytest.fixture
    def search(self, conn):
        return SqliteMemorySearchStore(conn)


def test_porter_stemming_matches_word_forms(conn):
    SqliteMemoryStore(conn).insert_record(record(content="Kang was running late"))
    hits = SqliteMemorySearchStore(conn).lexical("runs", LIVE, None, 10)
    assert [h.record_id for h in hits] == ["mem-1"]


@pytest.mark.parametrize(
    "query", ['robotics AND "team', "NEAR(robotics)", "robot*", "-robotics", "a:b"]
)
def test_fts_syntax_in_kangs_text_is_just_text(conn, query):
    SqliteMemoryStore(conn).insert_record(record(content="robotics team"))
    SqliteMemorySearchStore(conn).lexical(query, LIVE, None, 10)  # never raises


def test_fts_query_quotes_every_word():
    assert fts_query('say "hi" AND bye') == '"say" OR "hi" OR "AND" OR "bye"'
    assert fts_query("?!") == ""
