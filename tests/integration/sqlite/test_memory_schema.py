"""The memory-truth schema (ADR-048, migration 0020) — 07_DATABASE Part XVI's
"Schema" suite: every CHECK/FK/NOT NULL exercised with a violating insert
that must fail; enum exhaustiveness against 06_MEMORY's taxonomy; FTS5 sync
(including fts_memory's private exclusion); change capture (including D5's
statistics-only exemption); the provenance invariant; zero rows after the
full chain — nothing seeds (03_ROADMAP §3, "no gate bypass for bootstrapping"
starts here).
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.migrations import apply_migrations

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"
MIGRATION_0020 = MIGRATIONS_DIR / "0020_memory_truth_schema.sql"


@pytest.fixture
def conn(tmp_path):
    connection = open_connection(tmp_path / "kang.db")
    apply_migrations(connection, MIGRATIONS_DIR, FakeClock())
    yield connection
    connection.close()


# --------------------------------------------------------------- row builders


def _memory_record(conn, **overrides):
    base = dict(
        id="mem-1",
        type="fact",
        status="active",
        content="hello world",
        trust_tier=2,
        confidence=1.0,
        sensitivity="normal",
        content_enc=None,
        source_kind="stated",
        source_detail="conversation",
        source_quote=None,
        reason="kang said so",
        created_by="kang",
        created_at="2026-09-17T00:00:00Z",
        updated_at="2026-09-17T00:00:00Z",
        device_id="dev-1",
        revision=1,
        importance=0.5,
        pinned=0,
        last_accessed=None,
        access_count=0,
        embedding_ver=None,
    )
    base.update(overrides)
    cols = ", ".join(base)
    placeholders = ", ".join(f":{c}" for c in base)
    conn.execute(f"INSERT INTO memory_record ({cols}) VALUES ({placeholders})", base)


def _episode(conn, **overrides):
    base = dict(
        id="ep-1",
        type="plan",
        occurred_at="2026-09-17T00:00:00Z",
        content='{"k":"v"}',
        summary="a plan",
        status="active",
        compressed_into=None,
        source_kind="rule",
        source_detail="rule:planner",
        reason="daily plan",
        created_by="rule:planner",
        created_at="2026-09-17T00:00:00Z",
        updated_at="2026-09-17T00:00:00Z",
        device_id="dev-1",
        revision=1,
        embedding_ver=None,
    )
    base.update(overrides)
    cols = ", ".join(base)
    placeholders = ", ".join(f":{c}" for c in base)
    conn.execute(f"INSERT INTO episode ({cols}) VALUES ({placeholders})", base)


def _vault_note(conn, **overrides):
    base = dict(
        path="Notes/a.md",
        title="A",
        mtime="2026-09-17T00:00:00Z",
        size=10,
        content_hash="h1",
        indexed_at="2026-09-17T00:00:00Z",
        status="indexed",
    )
    base.update(overrides)
    cols = ", ".join(base)
    placeholders = ", ".join(f":{c}" for c in base)
    conn.execute(f"INSERT INTO vault_note ({cols}) VALUES ({placeholders})", base)


def _vault_chunk(conn, **overrides):
    base = dict(
        id="chunk-1",
        note_path="Notes/a.md",
        anchor=None,
        seq=1,
        content="excerpt text",
        token_est=3,
        embedding_ver=None,
    )
    base.update(overrides)
    cols = ", ".join(base)
    placeholders = ", ".join(f":{c}" for c in base)
    conn.execute(f"INSERT INTO vault_chunk ({cols}) VALUES ({placeholders})", base)


def _link(conn, **overrides):
    base = dict(
        id="link-1",
        src_kind="memory",
        src_id="mem-1",
        dst_kind="project",
        dst_id="proj-1",
        type="relates_to",
        status="active",
        created_by="kang",
        created_at="2026-09-17T00:00:00Z",
        reason=None,
        device_id="dev-1",
        revision=1,
    )
    base.update(overrides)
    cols = ", ".join(base)
    placeholders = ", ".join(f":{c}" for c in base)
    conn.execute(f"INSERT INTO link ({cols}) VALUES ({placeholders})", base)


def _candidate(conn, **overrides):
    base = dict(
        id="cand-1",
        payload='{"type":"fact"}',
        flags="[]",
        flag_context=None,
        proposed_at="2026-09-17T00:00:00Z",
        expires_at="2026-10-01T00:00:00Z",
        resolved=None,
        resolved_at=None,
    )
    base.update(overrides)
    cols = ", ".join(base)
    placeholders = ", ".join(f":{c}" for c in base)
    conn.execute(
        f"INSERT INTO memory_candidate_queue ({cols}) VALUES ({placeholders})", base
    )


def _embedding_version(conn, **overrides):
    base = dict(
        ver=1,
        model="local-e5",
        dim=768,
        created_at="2026-09-17T00:00:00Z",
        status="active",
    )
    base.update(overrides)
    cols = ", ".join(base)
    placeholders = ", ".join(f":{c}" for c in base)
    conn.execute(
        f"INSERT INTO embedding_version ({cols}) VALUES ({placeholders})", base
    )


# ------------------------------------------------------- zero rows after chain


def test_no_memory_truth_table_is_seeded(conn):
    for table in (
        "memory_record",
        "memory_revision",
        "memory_candidate_queue",
        "episode",
        "link",
        "link_index",
        "vault_note",
        "vault_chunk",
        "embedding_version",
    ):
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert count == 0, f"{table} seeded a row — no gate bypass for bootstrapping"


# ---------------------------------------------------------------- CHECK / NOT NULL / FK


def test_memory_record_type_rejects_a_value_outside_the_catalog(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _memory_record(conn, type="not-a-real-type")


@pytest.mark.parametrize("removed_status", ["candidate", "rejected"])
def test_memory_record_status_no_longer_accepts_the_removed_candidate_states(
    conn, removed_status
):
    """D1: a candidate lives only in memory_candidate_queue now."""
    with pytest.raises(sqlite3.IntegrityError):
        _memory_record(conn, status=removed_status)


def test_memory_record_status_rejects_an_unrecognized_value(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _memory_record(conn, status="not-a-real-status")


def test_memory_record_has_no_default_status(conn):
    """D1: the gate supplies 'active' explicitly; there is no default that
    could accidentally admit a row."""
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO memory_record (id, type, content, trust_tier, "
            "sensitivity, source_kind, source_detail, reason, created_by, "
            "created_at, updated_at, device_id) VALUES "
            "('mem-x','fact','c',2,'normal','stated','d','r','kang','c','u','dev')"
        )


@pytest.mark.parametrize("trust_tier", [-1, 3])
def test_memory_record_trust_tier_rejects_out_of_range(conn, trust_tier):
    with pytest.raises(sqlite3.IntegrityError):
        _memory_record(conn, trust_tier=trust_tier)


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_memory_record_confidence_rejects_out_of_range(conn, confidence):
    with pytest.raises(sqlite3.IntegrityError):
        _memory_record(conn, confidence=confidence)


@pytest.mark.parametrize("importance", [-0.01, 1.01])
def test_memory_record_importance_rejects_out_of_range(conn, importance):
    with pytest.raises(sqlite3.IntegrityError):
        _memory_record(conn, importance=importance)


def test_memory_record_pinned_rejects_outside_zero_one(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _memory_record(conn, pinned=2)


def test_memory_record_sensitivity_rejects_an_unrecognized_value(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _memory_record(conn, sensitivity="top-secret")


def test_memory_record_source_kind_rejects_an_unrecognized_value(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _memory_record(conn, source_kind="telepathy")


def test_memory_record_content_rejects_empty_string(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _memory_record(conn, content="")


def test_memory_record_reason_rejects_empty_string(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _memory_record(conn, reason="")


def test_private_record_with_plaintext_content_is_refused(conn):
    """DB-005 invariant, forward direction: private ⇒ ciphertext."""
    with pytest.raises(sqlite3.IntegrityError):
        _memory_record(
            conn, id="mem-priv", sensitivity="private", content="real secret text"
        )


def test_private_record_without_ciphertext_is_refused(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _memory_record(
            conn,
            id="mem-priv",
            sensitivity="private",
            content="[encrypted]",
            content_enc=None,
        )


def test_private_record_with_placeholder_and_ciphertext_is_accepted(conn):
    _memory_record(
        conn,
        id="mem-priv",
        sensitivity="private",
        content="[encrypted]",
        content_enc=b"\xde\xad\xbe\xef",
    )
    row = conn.execute(
        "SELECT content, content_enc FROM memory_record WHERE id = 'mem-priv'"
    ).fetchone()
    assert row == ("[encrypted]", b"\xde\xad\xbe\xef")


def test_memory_record_embedding_ver_referencing_missing_version_is_refused(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _memory_record(conn, embedding_ver=999)


def test_memory_record_embedding_ver_accepts_a_real_version(conn):
    _embedding_version(conn)
    _memory_record(conn, embedding_ver=1)
    row = conn.execute(
        "SELECT embedding_ver FROM memory_record WHERE id = 'mem-1'"
    ).fetchone()
    assert row == (1,)


def test_memory_revision_fk_to_missing_record_is_refused(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO memory_revision (record_id, revision, content, "
            "edited_by, edited_at) VALUES "
            "('no-such-record', 1, 'x', 'kang', '2026-09-17T00:00:00Z')"
        )


def test_memory_revision_cascades_on_record_delete(conn):
    _memory_record(conn)
    conn.execute(
        "INSERT INTO memory_revision (record_id, revision, content, "
        "edited_by, edited_at) VALUES "
        "('mem-1', 1, 'hello world', 'kang', '2026-09-17T00:00:00Z')"
    )
    conn.execute("DELETE FROM memory_record WHERE id = 'mem-1'")
    remaining = conn.execute(
        "SELECT COUNT(*) FROM memory_revision WHERE record_id = 'mem-1'"
    ).fetchone()[0]
    assert remaining == 0


def test_memory_candidate_queue_resolved_rejects_an_unrecognized_value(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _candidate(conn, resolved="maybe")


def test_episode_type_rejects_an_unrecognized_value(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _episode(conn, type="not-a-real-type")


def test_episode_status_rejects_an_unrecognized_value(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _episode(conn, status="not-a-real-status")


def test_episode_embedding_ver_referencing_missing_version_is_refused(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _episode(conn, embedding_ver=999)


def test_vault_chunk_fk_to_missing_note_is_refused(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _vault_chunk(conn, note_path="Notes/does-not-exist.md")


def test_vault_chunk_unique_note_path_seq_is_enforced(conn):
    _vault_note(conn)
    _vault_chunk(conn, id="chunk-1", seq=1)
    with pytest.raises(sqlite3.IntegrityError):
        _vault_chunk(conn, id="chunk-2", seq=1)


def test_vault_chunk_embedding_ver_referencing_missing_version_is_refused(conn):
    _vault_note(conn)
    with pytest.raises(sqlite3.IntegrityError):
        _vault_chunk(conn, embedding_ver=999)


def test_link_type_rejects_an_unrecognized_value(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _link(conn, type="not-a-real-type")


def test_link_status_rejects_an_unrecognized_value(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _link(conn, status="not-a-real-status")


def test_link_composite_unique_is_enforced(conn):
    _link(conn, id="link-1")
    with pytest.raises(sqlite3.IntegrityError):
        _link(conn, id="link-2")  # identical (src,dst,type)


def test_embedding_version_status_rejects_an_unrecognized_value(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _embedding_version(conn, status="not-a-real-status")


# -------------------------------------------- enum exhaustiveness against 06

# Expected sets sourced from docs/06_MEMORY.md, cited by line (read in this
# session, 2026-09-17): §2.1 type catalog (:97-118, both A and B tables),
# §9.1 link types (:405-418), §4.2's sensitivity/trust_tier lines are
# unchanged from 07 and not re-derived here. D1 (ADR-048) is the one
# deliberate exception encoded below: memory_record.status is 06's own
# candidate → active → ... machine (M-002) MINUS the two queue-resident
# states ('candidate','rejected').
_EXPECTED_MEMORY_TYPE = {
    "profile",
    "preference",
    "fact",
    "relationship",
    "lesson",
    "rule",
    "observation",
    "reflection",
}  # 06 §2.1A, :101-108
_EXPECTED_MEMORY_STATUS = {"active", "under_review", "superseded", "archived"}
# 06 M-002's machine minus 'candidate'/'rejected' (ADR-048 D1) — the two
# states that live in memory_candidate_queue instead (06 §2.1D)
_EXPECTED_EPISODE_TYPE = {"plan", "review", "retrospective", "session", "decision"}
# 06 §2.1B, :114-118
_EXPECTED_LINK_TYPE = {
    "relates_to",
    "derived_from",
    "supersedes",
    "superseded_by",
    "contradicts",
    "about_project",
    "about_competition",
    "about_goal",
    "about_person",
    "references_note",
    "from_conversation",
    "evidence_for",
    "evidence_against",
}  # 06 §9.1, :407-417


def _check_enum(sql_text: str, table: str, column: str) -> set[str]:
    """Extract the literal value set of `column`'s CHECK (column IN (...))
    from a CREATE TABLE block in the migration's own source text."""
    table_match = re.search(
        rf"CREATE TABLE {re.escape(table)} \((.*?)\n\);", sql_text, re.S
    )
    assert table_match, f"CREATE TABLE {table} not found in {MIGRATION_0020.name}"
    # Strip line comments first — 07's own DDL style puts multi-line prose
    # comments (e.g. link's src_kind/dst_kind value list) beside CHECK
    # clauses, and a stray ')' inside a comment would otherwise truncate
    # the captured enum early.
    block = "\n".join(
        line.split("--", 1)[0] for line in table_match.group(1).splitlines()
    )
    enum_match = re.search(
        rf"\b{re.escape(column)}\b[^,]*?CHECK\s*\(\s*{re.escape(column)}\s+IN\s*"
        r"\(([^)]*)\)",
        block,
        re.S,
    )
    assert enum_match, f"no CHECK enum found for {table}.{column}"
    return {v.strip().strip("'") for v in enum_match.group(1).split(",")}


@pytest.fixture(scope="module")
def migration_sql() -> str:
    return MIGRATION_0020.read_text(encoding="utf-8")


def test_memory_record_type_enum_matches_06_taxonomy(migration_sql):
    assert _check_enum(migration_sql, "memory_record", "type") == _EXPECTED_MEMORY_TYPE


def test_memory_record_status_enum_matches_d1s_narrowed_taxonomy(migration_sql):
    assert (
        _check_enum(migration_sql, "memory_record", "status") == _EXPECTED_MEMORY_STATUS
    )


def test_episode_type_enum_matches_06_taxonomy(migration_sql):
    assert _check_enum(migration_sql, "episode", "type") == _EXPECTED_EPISODE_TYPE


def test_link_type_enum_matches_06_taxonomy(migration_sql):
    assert _check_enum(migration_sql, "link", "type") == _EXPECTED_LINK_TYPE


# ----------------------------------------------------------------------- FTS


def test_fts_memory_sync_insert_update_delete(conn):
    _memory_record(conn, id="mem-1", content="alpha bravo")
    hits = conn.execute(
        "SELECT rowid FROM fts_memory WHERE fts_memory MATCH 'alpha'"
    ).fetchall()
    assert hits == [(1,)]

    conn.execute("UPDATE memory_record SET content = 'charlie' WHERE id = 'mem-1'")
    assert (
        conn.execute(
            "SELECT rowid FROM fts_memory WHERE fts_memory MATCH 'alpha'"
        ).fetchall()
        == []
    )
    assert conn.execute(
        "SELECT rowid FROM fts_memory WHERE fts_memory MATCH 'charlie'"
    ).fetchall() == [(1,)]

    conn.execute("DELETE FROM memory_record WHERE id = 'mem-1'")
    assert (
        conn.execute(
            "SELECT rowid FROM fts_memory WHERE fts_memory MATCH 'charlie'"
        ).fetchall()
        == []
    )
    conn.execute("INSERT INTO fts_memory(fts_memory) VALUES ('integrity-check')")


def test_fts_memory_never_indexes_a_private_record(conn):
    _memory_record(
        conn,
        id="mem-priv",
        sensitivity="private",
        content="[encrypted]",
        content_enc=b"\x01",
    )
    assert (
        conn.execute(
            "SELECT rowid FROM fts_memory WHERE fts_memory MATCH 'encrypted'"
        ).fetchall()
        == []
    )
    conn.execute("INSERT INTO fts_memory(fts_memory) VALUES ('integrity-check')")


def test_fts_memory_flip_to_private_removes_it_from_the_index(conn):
    _memory_record(conn, id="mem-1", sensitivity="normal", content="findme")
    assert conn.execute(
        "SELECT rowid FROM fts_memory WHERE fts_memory MATCH 'findme'"
    ).fetchall() == [(1,)]

    conn.execute(
        "UPDATE memory_record SET sensitivity = 'private', content = '[encrypted]', "
        "content_enc = x'01' WHERE id = 'mem-1'"
    )
    assert (
        conn.execute(
            "SELECT rowid FROM fts_memory WHERE fts_memory MATCH 'findme'"
        ).fetchall()
        == []
    )
    conn.execute("INSERT INTO fts_memory(fts_memory) VALUES ('integrity-check')")


def test_fts_memory_flip_from_private_indexes_it(conn):
    _memory_record(
        conn,
        id="mem-1",
        sensitivity="private",
        content="[encrypted]",
        content_enc=b"\x01",
    )
    conn.execute(
        "UPDATE memory_record SET sensitivity = 'normal', content = 'now visible' "
        "WHERE id = 'mem-1'"
    )
    assert conn.execute(
        "SELECT rowid FROM fts_memory WHERE fts_memory MATCH 'visible'"
    ).fetchall() == [(1,)]
    conn.execute("INSERT INTO fts_memory(fts_memory) VALUES ('integrity-check')")


def test_fts_memory_deleting_a_private_row_leaves_the_index_intact(conn):
    _memory_record(
        conn,
        id="mem-priv",
        sensitivity="private",
        content="[encrypted]",
        content_enc=b"\x01",
    )
    conn.execute("DELETE FROM memory_record WHERE id = 'mem-priv'")
    # No exception on integrity-check: a 'delete' command was never issued
    # for a rowid fts5 never saw, which would corrupt the index.
    conn.execute("INSERT INTO fts_memory(fts_memory) VALUES ('integrity-check')")


def test_fts_episode_sync_insert_update_delete(conn):
    _episode(conn, id="ep-1", content="delta echo")
    assert conn.execute(
        "SELECT rowid FROM fts_episode WHERE fts_episode MATCH 'delta'"
    ).fetchall() == [(1,)]

    conn.execute("UPDATE episode SET content = 'foxtrot' WHERE id = 'ep-1'")
    assert (
        conn.execute(
            "SELECT rowid FROM fts_episode WHERE fts_episode MATCH 'delta'"
        ).fetchall()
        == []
    )
    assert conn.execute(
        "SELECT rowid FROM fts_episode WHERE fts_episode MATCH 'foxtrot'"
    ).fetchall() == [(1,)]

    conn.execute("DELETE FROM episode WHERE id = 'ep-1'")
    assert (
        conn.execute(
            "SELECT rowid FROM fts_episode WHERE fts_episode MATCH 'foxtrot'"
        ).fetchall()
        == []
    )
    conn.execute("INSERT INTO fts_episode(fts_episode) VALUES ('integrity-check')")


def test_fts_chunk_sync_insert_update_delete(conn):
    _vault_note(conn)
    _vault_chunk(conn, id="chunk-1", content="golf hotel")
    assert conn.execute(
        "SELECT rowid FROM fts_chunk WHERE fts_chunk MATCH 'golf'"
    ).fetchall() == [(1,)]

    conn.execute("UPDATE vault_chunk SET content = 'india' WHERE id = 'chunk-1'")
    assert (
        conn.execute(
            "SELECT rowid FROM fts_chunk WHERE fts_chunk MATCH 'golf'"
        ).fetchall()
        == []
    )
    assert conn.execute(
        "SELECT rowid FROM fts_chunk WHERE fts_chunk MATCH 'india'"
    ).fetchall() == [(1,)]

    conn.execute("DELETE FROM vault_chunk WHERE id = 'chunk-1'")
    assert (
        conn.execute(
            "SELECT rowid FROM fts_chunk WHERE fts_chunk MATCH 'india'"
        ).fetchall()
        == []
    )
    conn.execute("INSERT INTO fts_chunk(fts_chunk) VALUES ('integrity-check')")


def test_fts_message_sync_insert_update_delete(conn):
    conn.execute(
        "INSERT INTO conversation (id, started, last_message) VALUES "
        "('conv-1', '2026-09-17T00:00:00Z', '2026-09-17T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO message (id, conversation_id, role, content, at) VALUES "
        "('msg-1', 'conv-1', 'kang', 'juliet kilo', '2026-09-17T00:00:00Z')"
    )
    assert conn.execute(
        "SELECT rowid FROM fts_message WHERE fts_message MATCH 'juliet'"
    ).fetchall() == [(1,)]

    conn.execute("UPDATE message SET content = 'lima' WHERE id = 'msg-1'")
    assert (
        conn.execute(
            "SELECT rowid FROM fts_message WHERE fts_message MATCH 'juliet'"
        ).fetchall()
        == []
    )
    assert conn.execute(
        "SELECT rowid FROM fts_message WHERE fts_message MATCH 'lima'"
    ).fetchall() == [(1,)]

    conn.execute("DELETE FROM message WHERE id = 'msg-1'")
    assert (
        conn.execute(
            "SELECT rowid FROM fts_message WHERE fts_message MATCH 'lima'"
        ).fetchall()
        == []
    )
    conn.execute("INSERT INTO fts_message(fts_message) VALUES ('integrity-check')")


# ------------------------------------------------------------- change capture


def test_memory_record_insert_update_delete_are_each_captured(conn):
    _memory_record(conn, id="mem-1")
    conn.execute("UPDATE memory_record SET content = 'changed' WHERE id = 'mem-1'")
    conn.execute("DELETE FROM memory_record WHERE id = 'mem-1'")
    ops = conn.execute(
        "SELECT op FROM change_log WHERE entity = 'memory_record' "
        "AND entity_id = 'mem-1' ORDER BY seq"
    ).fetchall()
    assert ops == [("insert",), ("update",), ("delete",)]


def test_memory_record_statistics_only_update_is_not_captured(conn):
    _memory_record(conn, id="mem-1")
    before = conn.execute(
        "SELECT COUNT(*) FROM change_log WHERE entity = 'memory_record' "
        "AND entity_id = 'mem-1'"
    ).fetchone()[0]
    conn.execute(
        "UPDATE memory_record SET last_accessed = '2026-09-17T01:00:00Z', "
        "access_count = access_count + 1 WHERE id = 'mem-1'"
    )
    after = conn.execute(
        "SELECT COUNT(*) FROM change_log WHERE entity = 'memory_record' "
        "AND entity_id = 'mem-1'"
    ).fetchone()[0]
    assert after == before  # D5: statistics-only writes never capture


def test_memory_revision_insert_is_captured_with_the_owning_records_device(conn):
    _memory_record(conn, id="mem-1", device_id="dev-xyz")
    conn.execute(
        "INSERT INTO memory_revision (record_id, revision, content, "
        "edited_by, edited_at) VALUES "
        "('mem-1', 1, 'hello world', 'kang', '2026-09-17T00:00:00Z')"
    )
    row = conn.execute(
        "SELECT entity, entity_id, op, device_id FROM change_log "
        "WHERE entity = 'memory_revision'"
    ).fetchone()
    assert row == ("memory_revision", "mem-1", "insert", "dev-xyz")


def test_episode_insert_update_delete_are_each_captured(conn):
    _episode(conn, id="ep-1")
    conn.execute("UPDATE episode SET summary = 'changed' WHERE id = 'ep-1'")
    conn.execute("DELETE FROM episode WHERE id = 'ep-1'")
    ops = conn.execute(
        "SELECT op FROM change_log WHERE entity = 'episode' AND entity_id = 'ep-1' "
        "ORDER BY seq"
    ).fetchall()
    assert ops == [("insert",), ("update",), ("delete",)]


def test_link_insert_update_delete_are_each_captured(conn):
    _link(conn, id="link-1")
    conn.execute("UPDATE link SET status = 'retired' WHERE id = 'link-1'")
    conn.execute("DELETE FROM link WHERE id = 'link-1'")
    ops = conn.execute(
        "SELECT op FROM change_log WHERE entity = 'link' AND entity_id = 'link-1' "
        "ORDER BY seq"
    ).fetchall()
    assert ops == [("insert",), ("update",), ("delete",)]


def test_memory_candidate_queue_writes_are_never_captured(conn):
    _candidate(conn, id="cand-1")
    conn.execute(
        "UPDATE memory_candidate_queue SET flags = '[\"x\"]' WHERE id = 'cand-1'"
    )
    conn.execute("DELETE FROM memory_candidate_queue WHERE id = 'cand-1'")
    count = conn.execute(
        "SELECT COUNT(*) FROM change_log WHERE entity = 'memory_candidate_queue'"
    ).fetchone()[0]
    assert count == 0


def test_link_index_writes_are_never_captured(conn):
    conn.execute(
        "INSERT INTO link_index (src, dst, type, origin) VALUES "
        "('memory:mem-1', 'project:proj-1', 'relates_to', 'link')"
    )
    conn.execute("DELETE FROM link_index")
    count = conn.execute(
        "SELECT COUNT(*) FROM change_log WHERE entity = 'link_index'"
    ).fetchone()[0]
    assert count == 0


def test_vault_note_writes_are_never_captured(conn):
    _vault_note(conn)
    conn.execute("UPDATE vault_note SET status = 'stale' WHERE path = 'Notes/a.md'")
    conn.execute("DELETE FROM vault_note WHERE path = 'Notes/a.md'")
    count = conn.execute(
        "SELECT COUNT(*) FROM change_log WHERE entity = 'vault_note'"
    ).fetchone()[0]
    assert count == 0


def test_vault_chunk_writes_are_never_captured(conn):
    _vault_note(conn)
    _vault_chunk(conn, id="chunk-1")
    conn.execute("UPDATE vault_chunk SET content = 'x' WHERE id = 'chunk-1'")
    conn.execute("DELETE FROM vault_chunk WHERE id = 'chunk-1'")
    count = conn.execute(
        "SELECT COUNT(*) FROM change_log WHERE entity = 'vault_chunk'"
    ).fetchone()[0]
    assert count == 0


def test_embedding_version_writes_are_never_captured(conn):
    _embedding_version(conn)
    conn.execute("UPDATE embedding_version SET status = 'retired' WHERE ver = 1")
    conn.execute("DELETE FROM embedding_version WHERE ver = 1")
    count = conn.execute(
        "SELECT COUNT(*) FROM change_log WHERE entity = 'embedding_version'"
    ).fetchone()[0]
    assert count == 0


# ------------------------------------------------------ provenance invariant


@pytest.mark.parametrize(
    "table,columns",
    [
        (
            "memory_record",
            ["source_kind", "source_detail", "reason", "created_by", "created_at"],
        ),
        (
            "episode",
            ["source_kind", "source_detail", "reason", "created_by", "created_at"],
        ),
        ("link", ["created_by", "created_at"]),
    ],
)
def test_provenance_columns_are_not_null(conn, table, columns):
    """07 Part XIII.5: migration 0020 weakens no provenance column — every
    provenance field on every new truth table stays NOT NULL, as 07's own
    DDL declares it (Memory Part VIII: missing provenance is a schema
    violation, not a warning)."""
    info = {row[1]: row[3] for row in conn.execute(f"PRAGMA table_info({table})")}
    for column in columns:
        assert info[column] == 1, f"{table}.{column} must be NOT NULL"
