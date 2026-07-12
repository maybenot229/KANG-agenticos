"""Migration harness proofs (07 Part XIII; 13 §2.11 skeleton).

Full chain on empty; checksum immutability (a modified historical migration
is startup-blocking); gapless numbering; atomic failure.
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from pathlib import Path

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.migrations import MigrationError, apply_migrations, discover

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"


@pytest.fixture
def conn(tmp_path):
    connection = open_connection(tmp_path / "kang.db")
    yield connection
    connection.close()


def test_full_chain_applies_on_empty_database(conn):
    applied = apply_migrations(conn, MIGRATIONS_DIR, FakeClock())
    assert applied == [1]
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"schema_version", "change_log", "tombstone", "task"} <= tables


def test_applied_checksum_matches_the_file(conn):
    apply_migrations(conn, MIGRATIONS_DIR, FakeClock())
    stored = conn.execute(
        "SELECT checksum FROM schema_version WHERE version = 1"
    ).fetchone()[0]
    expected = hashlib.sha256(
        (MIGRATIONS_DIR / "0001_initial.sql").read_bytes()
    ).hexdigest()
    assert stored == expected


def test_reapply_is_a_noop(conn):
    apply_migrations(conn, MIGRATIONS_DIR, FakeClock())
    assert apply_migrations(conn, MIGRATIONS_DIR, FakeClock()) == []


def test_modified_historical_migration_blocks_startup(tmp_path):
    shipped = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS_DIR, shipped)
    conn = open_connection(tmp_path / "kang.db")
    apply_migrations(conn, shipped, FakeClock())
    target = shipped / "0001_initial.sql"
    target.write_text(
        target.read_text(encoding="utf-8") + "\n-- tampered\n", encoding="utf-8"
    )
    with pytest.raises(MigrationError, match="modified"):
        apply_migrations(conn, shipped, FakeClock())
    conn.close()


def test_missing_applied_migration_blocks_startup(tmp_path, conn):
    shipped = tmp_path / "empty_migrations"
    shipped.mkdir()
    apply_migrations(conn, MIGRATIONS_DIR, FakeClock())
    with pytest.raises(MigrationError, match="missing from the shipped set"):
        apply_migrations(conn, shipped, FakeClock())


def test_version_gaps_are_rejected(tmp_path):
    shipped = tmp_path / "migrations"
    shipped.mkdir()
    (shipped / "0002_orphan.sql").write_text("CREATE TABLE x (id TEXT);")
    with pytest.raises(MigrationError, match="gapless"):
        discover(shipped)


def test_malformed_filenames_are_rejected(tmp_path):
    shipped = tmp_path / "migrations"
    shipped.mkdir()
    (shipped / "001_short.sql").write_text("CREATE TABLE x (id TEXT);")
    with pytest.raises(MigrationError, match="NNNN_description"):
        discover(shipped)


def test_failed_migration_leaves_no_partial_truth(tmp_path):
    shipped = tmp_path / "migrations"
    shipped.mkdir()
    (shipped / "0001_bad.sql").write_text(
        "CREATE TABLE half_done (id TEXT PRIMARY KEY);\n"
        "CREATE TABLE broken (id TEXT PRIMARY KEY;\n"  # syntax error
    )
    conn = open_connection(tmp_path / "kang.db")
    with pytest.raises(MigrationError, match="0001 failed"):
        apply_migrations(conn, shipped, FakeClock())
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("SELECT id FROM half_done")
    assert conn.execute("SELECT COUNT(version) FROM schema_version").fetchone()[0] == 0
    conn.close()
