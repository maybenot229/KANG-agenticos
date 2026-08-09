"""SqliteGoalStore against the real schema (ADR-016's write path)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.goal_store import SqliteGoalStore
from kang.adapters.sqlite.migrations import apply_migrations
from kang.domain.projects.goal_service import GoalDraft, create_goal

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"


@pytest.fixture
def conn(tmp_path):
    connection = open_connection(tmp_path / "kang.db")
    apply_migrations(connection, MIGRATIONS_DIR, FakeClock())
    yield connection
    connection.close()


def _goal(index: int, **overrides):
    draft = GoalDraft(
        title=overrides.pop("title", f"Goal {index}"),
        horizon=overrides.pop("horizon", "quarter"),
        **overrides,
    )
    return create_goal(draft, f"goal-{index:04d}", FakeClock(), device_id="dev")


def test_create_then_list_all(conn):
    store = SqliteGoalStore(conn)
    store.create(_goal(0, title="Zebra goal"))
    store.create(_goal(1, title="alpha goal"))
    titles = [g.title for g in store.list_all()]
    # title COLLATE NOCASE, id — "alpha" sorts before "Zebra" case-insensitively
    assert titles == ["alpha goal", "Zebra goal"]


def test_list_all_carries_every_field(conn):
    store = SqliteGoalStore(conn)
    store.create(_goal(0, horizon="year", description="Ranked list, 1 = highest"))
    (goal,) = store.list_all()
    assert goal.horizon == "year"
    assert goal.description == "Ranked list, 1 = highest"
    assert goal.status == "active"
    assert goal.revision == 1


def test_survives_reopen(tmp_path):
    first = open_connection(tmp_path / "kang.db")
    apply_migrations(first, MIGRATIONS_DIR, FakeClock())
    SqliteGoalStore(first).create(_goal(0))
    first.close()
    second = open_connection(tmp_path / "kang.db")
    assert [g.id for g in SqliteGoalStore(second).list_all()] == ["goal-0000"]
    second.close()


def test_horizon_check_constraint_is_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO goal (id, title, horizon, status, created_at, "
            "updated_at, device_id, revision) VALUES "
            "('g', 't', 'bogus', 'active', 'c', 'u', 'dev', 1)"
        )


def test_status_check_constraint_is_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO goal (id, title, horizon, status, created_at, "
            "updated_at, device_id, revision) VALUES "
            "('g', 't', 'quarter', 'bogus', 'c', 'u', 'dev', 1)"
        )


def test_create_writes_a_change_log_row(conn):
    # ADR-016: goal's first write path, and the change-capture trigger
    # (migration 0014) that arrived with it — 07 §5.6's "exercised from
    # day one" is not automatic; this proves the trigger actually fires.
    SqliteGoalStore(conn).create(_goal(0))
    captured = conn.execute(
        "SELECT entity, entity_id, op FROM change_log WHERE entity = 'goal'"
    ).fetchall()
    assert captured == [("goal", "goal-0000", "insert")]
