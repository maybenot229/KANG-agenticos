"""SqliteProjectStore against the real schema (ADR-013's write path)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.migrations import apply_migrations
from kang.adapters.sqlite.project_store import SqliteProjectStore
from kang.domain.projects.project_service import ProjectDraft, create_project

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"


@pytest.fixture
def conn(tmp_path):
    connection = open_connection(tmp_path / "kang.db")
    apply_migrations(connection, MIGRATIONS_DIR, FakeClock())
    yield connection
    connection.close()


def _project(index: int, **overrides):
    draft = ProjectDraft(name=overrides.pop("name", f"Project {index}"), **overrides)
    return create_project(draft, f"proj-{index:04d}", FakeClock(), device_id="dev")


def test_create_then_list_all(conn):
    store = SqliteProjectStore(conn)
    store.create(_project(0, name="Zebra project"))
    store.create(_project(1, name="alpha project"))
    names = [p.name for p in store.list_all()]
    # name COLLATE NOCASE, id — "alpha" sorts before "Zebra" case-insensitively
    assert names == ["alpha project", "Zebra project"]


def test_list_all_carries_every_field(conn):
    store = SqliteProjectStore(conn)
    store.create(
        _project(
            0,
            description="Ship the agentic OS",
            vault_folder="KANG OS",
            github_repo="maybenot229/KANG",
        )
    )
    (project,) = store.list_all()
    assert project.description == "Ship the agentic OS"
    assert project.vault_folder == "KANG OS"
    assert project.github_repo == "maybenot229/KANG"
    assert project.status == "active"
    assert project.revision == 1


def test_survives_reopen(tmp_path):
    first = open_connection(tmp_path / "kang.db")
    apply_migrations(first, MIGRATIONS_DIR, FakeClock())
    SqliteProjectStore(first).create(_project(0))
    first.close()
    second = open_connection(tmp_path / "kang.db")
    assert [p.id for p in SqliteProjectStore(second).list_all()] == ["proj-0000"]
    second.close()


def test_status_check_constraint_is_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO project (id, name, status, created_at, updated_at, "
            "device_id, revision) VALUES ('p', 'n', 'bogus', 'c', 'u', 'dev', 1)"
        )


def test_create_writes_a_change_log_row(conn):
    # ADR-013: project's first write path, and the change-capture trigger
    # (migration 0011) that arrived with it — 07 §5.6's "exercised from
    # day one" is not automatic; this proves the trigger actually fires.
    SqliteProjectStore(conn).create(_project(0))
    captured = conn.execute(
        "SELECT entity, entity_id, op FROM change_log WHERE entity = 'project'"
    ).fetchall()
    assert captured == [("project", "proj-0000", "insert")]
