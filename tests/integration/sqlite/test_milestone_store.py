"""SqliteMilestoneStore against the real schema (ADR-015's write path)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.migrations import apply_migrations
from kang.adapters.sqlite.milestone_store import SqliteMilestoneStore
from kang.domain.ports.milestone_store import (
    MilestoneNotFoundError,
    MilestoneRevisionConflictError,
)
from kang.domain.projects.milestone_service import (
    MilestoneDraft,
    create_milestone,
    mark_reached,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"


@pytest.fixture
def conn(tmp_path):
    connection = open_connection(tmp_path / "kang.db")
    apply_migrations(connection, MIGRATIONS_DIR, FakeClock())
    yield connection
    connection.close()


def _seed_project(conn, project_id: str = "proj-1") -> None:
    conn.execute(
        "INSERT INTO project (id, name, status, created_at, updated_at, "
        "device_id, revision) VALUES (?, 'Fixture project', 'active', "
        "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', "
        "'device-test', 1)",
        (project_id,),
    )


def _milestone(index: int, **overrides):
    project_id = overrides.pop("project_id", "proj-1")
    title = overrides.pop("title", f"Milestone {index}")
    draft = MilestoneDraft(project_id=project_id, title=title, **overrides)
    return create_milestone(draft, f"ms-{index:04d}", FakeClock(), device_id="dev")


def test_create_then_list_for_project(conn):
    _seed_project(conn)
    store = SqliteMilestoneStore(conn, FakeClock())
    store.create(_milestone(0, due="2026-06-01T00:00:00+00:00"))
    store.create(_milestone(1, due="2026-03-01T00:00:00+00:00"))
    store.create(_milestone(2))  # undated — sorts last
    titles = [m.title for m in store.list_for_project("proj-1")]
    assert titles == ["Milestone 1", "Milestone 0", "Milestone 2"]


def test_list_for_project_scopes_to_that_project_only(conn):
    _seed_project(conn, "proj-1")
    _seed_project(conn, "proj-2")
    store = SqliteMilestoneStore(conn, FakeClock())
    store.create(_milestone(0, project_id="proj-1"))
    store.create(_milestone(1, project_id="proj-2"))
    assert [m.id for m in store.list_for_project("proj-1")] == ["ms-0000"]
    assert [m.id for m in store.list_for_project("proj-2")] == ["ms-0001"]


def test_unknown_project_id_is_rejected_by_the_fk_constraint(conn):
    store = SqliteMilestoneStore(conn, FakeClock())
    with pytest.raises(sqlite3.IntegrityError):
        store.create(_milestone(0, project_id="no-such-project"))


def test_status_check_constraint_is_enforced(conn):
    _seed_project(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO milestone (id, project_id, title, status, "
            "created_at, updated_at, device_id, revision) VALUES "
            "('m', 'proj-1', 't', 'bogus', 'c', 'u', 'dev', 1)"
        )


def test_create_writes_a_change_log_row(conn):
    # ADR-015: milestone's first write path, and the change-capture
    # trigger (migration 0013) that arrived with it — proven firing.
    _seed_project(conn)
    SqliteMilestoneStore(conn, FakeClock()).create(_milestone(0))
    captured = conn.execute(
        "SELECT entity, entity_id, op FROM change_log WHERE entity = 'milestone'"
    ).fetchall()
    assert captured == [("milestone", "ms-0000", "insert")]


def test_get_unknown_id_raises_typed_not_found(conn):
    with pytest.raises(MilestoneNotFoundError):
        SqliteMilestoneStore(conn, FakeClock()).get("ms-ghost")


def test_update_bumps_revision_and_updated_at(conn):
    _seed_project(conn)
    clock = FakeClock()
    store = SqliteMilestoneStore(conn, clock)
    milestone = _milestone(0)
    store.create(milestone)
    clock.advance(60)
    committed = store.update(mark_reached(milestone, clock))
    assert committed.revision == 2
    assert committed.updated_at == clock.now()
    assert committed.status == "reached"
    assert store.get(milestone.id) == committed


def test_update_with_stale_revision_conflicts(conn):
    _seed_project(conn)
    clock = FakeClock()
    store = SqliteMilestoneStore(conn, clock)
    milestone = _milestone(0)
    store.create(milestone)
    store.update(mark_reached(milestone, clock))
    with pytest.raises(MilestoneRevisionConflictError):
        store.update(mark_reached(milestone, clock))  # still revision 1


def test_update_capture_names_the_changed_fields(conn):
    _seed_project(conn)
    clock = FakeClock()
    store = SqliteMilestoneStore(conn, clock)
    milestone = _milestone(0)
    store.create(milestone)
    store.update(mark_reached(milestone, clock))
    fields, revision = conn.execute(
        "SELECT fields, revision FROM change_log WHERE op = 'update'"
    ).fetchone()
    assert set(json.loads(fields)) == {"status"}
    assert revision == 2


def test_deleting_the_parent_project_cascades_and_captures_the_delete(conn):
    # 07_DATABASE Appendix B: project -> milestone is a pre-sanctioned
    # CASCADE. Confirms two things at once: the CASCADE actually removes
    # the milestone row, and SQLite fires the milestone's own AFTER DELETE
    # trigger for FK-driven deletes (not just direct DELETE statements) —
    # true by default since 3.6.18, verified here rather than assumed.
    _seed_project(conn)
    SqliteMilestoneStore(conn, FakeClock()).create(_milestone(0))
    conn.execute("DELETE FROM project WHERE id = 'proj-1'")
    remaining = conn.execute("SELECT COUNT(*) FROM milestone").fetchone()[0]
    assert remaining == 0
    captured = conn.execute(
        "SELECT entity, entity_id, op FROM change_log WHERE entity = 'milestone' "
        "AND op = 'delete'"
    ).fetchall()
    assert captured == [("milestone", "ms-0000", "delete")]
