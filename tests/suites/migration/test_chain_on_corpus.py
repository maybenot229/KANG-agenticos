"""The migration chain on a populated database (13 §2.11; 07 Part XVI
"Migration" row; ADR-049 D5).

What "N-1 -> N on the corpus" means today: the corpus is generated at HEAD
(the generator itself applies `0001`..HEAD through the real harness), so this
suite proves the chain's *result* holds at scale — re-applying it against the
populated file is a no-op, the recorded history matches the shipped files
byte for byte, the database is structurally sound, and a `VACUUM INTO`
snapshot (07 Part XII, the only sanctioned backup) of the populated file
reopens intact. A future schema-changing migration's own test seeds pre-shape
rows by hand (the `0006`/`0020`/`0021` pattern); this suite then proves the
chain still applies over a decade-scale population.

`year1` runs in every build; `year10` is `nightly`-marked (ADR-049 D5).
"""

from __future__ import annotations

import hashlib

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.migrations import apply_migrations, discover
from tests.fixtures.corpus.generate import DIGEST_TABLES, MIGRATIONS_DIR

CORPORA = [
    "corpus_year1",
    pytest.param("corpus_year10", marks=pytest.mark.nightly),
]
FTS_TABLES = ("fts_memory", "fts_episode", "fts_chunk", "fts_message")


@pytest.fixture(params=CORPORA)
def populated(request, tmp_path):
    corpus = request.getfixturevalue(request.param)
    conn = open_connection(corpus.path)
    yield corpus, conn, tmp_path
    conn.close()


def test_reapplying_the_chain_on_a_populated_database_is_a_noop(populated):
    corpus, conn, _ = populated
    before = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in DIGEST_TABLES
    }
    assert apply_migrations(conn, MIGRATIONS_DIR, FakeClock()) == []
    after = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in DIGEST_TABLES
    }
    assert before == after == corpus.report.counts


def test_recorded_history_matches_every_shipped_migration_file(populated):
    _, conn, _ = populated
    recorded = dict(conn.execute("SELECT version, checksum FROM schema_version"))
    shipped = {
        m.version: hashlib.sha256(m.path.read_bytes()).hexdigest()
        for m in discover(MIGRATIONS_DIR)
    }
    assert recorded == shipped


def test_populated_database_is_structurally_sound(populated):
    _, conn, _ = populated
    assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    for fts in FTS_TABLES:
        conn.execute(f"INSERT INTO {fts}({fts}) VALUES ('integrity-check')")


def test_a_vacuum_into_snapshot_of_the_populated_file_reopens_intact(populated):
    corpus, conn, tmp_path = populated
    snapshot = tmp_path / "snapshot.db"
    conn.execute(f"VACUUM INTO '{snapshot}'")
    copy = open_connection(snapshot)
    try:
        assert copy.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        for table in ("memory_record", "episode", "vault_chunk", "link", "message"):
            assert (
                copy.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                == corpus.report.counts[table]
            )
        assert apply_migrations(copy, MIGRATIONS_DIR, FakeClock()) == []
    finally:
        copy.close()
