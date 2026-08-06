"""SqliteCompetitionStore against the real schema (ADR-014's write path)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.competition_store import SqliteCompetitionStore
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.migrations import apply_migrations
from kang.domain.competitions.competition_service import (
    CompetitionDraft,
    create_competition,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"


@pytest.fixture
def conn(tmp_path):
    connection = open_connection(tmp_path / "kang.db")
    apply_migrations(connection, MIGRATIONS_DIR, FakeClock())
    yield connection
    connection.close()


def _competition(index: int, **overrides):
    name = overrides.pop("name", f"Competition {index}")
    draft = CompetitionDraft(name=name, **overrides)
    return create_competition(draft, f"comp-{index:04d}", FakeClock(), device_id="dev")


def test_create_then_list_all(conn):
    store = SqliteCompetitionStore(conn)
    store.create(_competition(0, name="Zebra open"))
    store.create(_competition(1, name="alpha open"))
    names = [c.name for c in store.list_all()]
    assert names == ["alpha open", "Zebra open"]


def test_list_all_carries_every_field(conn):
    store = SqliteCompetitionStore(conn)
    store.create(_competition(0, url="https://usaco.org", project_id=None))
    (competition,) = store.list_all()
    assert competition.url == "https://usaco.org"
    assert competition.status == "discovered"
    assert competition.evaluation is None
    assert competition.result is None
    assert competition.revision == 1


def test_survives_reopen(tmp_path):
    first = open_connection(tmp_path / "kang.db")
    apply_migrations(first, MIGRATIONS_DIR, FakeClock())
    SqliteCompetitionStore(first).create(_competition(0))
    first.close()
    second = open_connection(tmp_path / "kang.db")
    assert [c.id for c in SqliteCompetitionStore(second).list_all()] == ["comp-0000"]
    second.close()


def test_status_check_constraint_is_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO competition (id, name, status, created_at, updated_at, "
            "device_id, revision) VALUES ('c', 'n', 'bogus', 'c', 'u', 'dev', 1)"
        )


def test_create_writes_a_change_log_row(conn):
    # ADR-014: competition's first write path, and the change-capture
    # trigger (migration 0012) that arrived with it — proven firing.
    SqliteCompetitionStore(conn).create(_competition(0))
    captured = conn.execute(
        "SELECT entity, entity_id, op FROM change_log WHERE entity = 'competition'"
    ).fetchall()
    assert captured == [("competition", "comp-0000", "insert")]
