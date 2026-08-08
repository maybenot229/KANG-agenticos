"""Payload-sufficiency suite (15 §16.2 / EB-003) — a standing obligation:
for every recovery-grade event type, applying the fixture event to an EMPTY
store yields the recorded row. A recovery-grade type without this proof
fails CI (a thinned payload silently breaks crash recovery).

This test is registry-driven: it iterates the event registry, so a future
recovery-grade type with no fixture here fails loudly rather than silently
skipping the guarantee.

`lead_days` is the one field whose stored form differs from its payload
form — a JSON array in the envelope, JSON text in the column (the adapter
translates at the port line, 17 §4.3.5). The comparison decodes it rather
than asserting the shapes are identical, because "the row reconstructs" is
the claim, not "the bytes match".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.migrations import apply_migrations
from kang.adapters.sqlite.recovery import SqliteRecoveryApplier
from kang.domain.ports.eventlog import EventEnvelope
from kang.kernel.bus.event_registry import EVENT_TYPES
from tests.fixtures.event_log_contract import make_envelope, task_payload

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"

_TASK_COLUMNS = (
    "id, project_id, title, notes, status, priority, due, plan_date, "
    "estimate_min, actual_min, completed_at, created_at, updated_at, "
    "device_id, revision"
)

_DEADLINE_COLUMNS = (
    "id, competition_id, project_id, kind, title, at, lead_days, status, "
    "created_at, updated_at, device_id, revision"
)

_PROJECT_COLUMNS = (
    "id, name, description, status, vault_folder, github_repo, goal_id, "
    "created_at, updated_at, device_id, revision"
)

_COMPETITION_COLUMNS = (
    "id, name, url, status, evaluation, result, project_id, created_at, "
    "updated_at, device_id, revision"
)

_MILESTONE_COLUMNS = (
    "id, project_id, title, due, status, created_at, updated_at, device_id, revision"
)


def deadline_payload(index: int = 0, **overrides) -> dict:
    """A self-sufficient deadline payload (EB-003) — the full 07 §5.2 field
    set, matching `deadline_service.deadline_event_payload()`."""
    payload = {
        "id": f"dl-{index:04d}",
        "competition_id": None,
        "project_id": None,
        "kind": "custom",
        "title": "submit the entry",
        "at": "2026-03-01T09:00:00+00:00",
        "lead_days": [14, 7, 3, 1],
        "status": "tracked",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "device_id": "device-test",
        "revision": 1,
    }
    payload.update(overrides)
    return payload


def _deadline_envelope(**overrides) -> EventEnvelope:
    fields = dict(
        type="deadline.created",
        payload=deadline_payload(0),
        entity_refs=({"kind": "deadline", "id": "dl-0000"},),
    )
    fields.update(overrides)
    return make_envelope(0, **fields)


def project_payload(index: int = 0, **overrides) -> dict:
    """A self-sufficient project payload (ADR-013/EB-003) — the full
    07 §5.2 field set, matching `project_service.project_event_payload()`."""
    payload = {
        "id": f"proj-{index:04d}",
        "name": "KANG v0.1",
        "description": "Ship the agentic OS",
        "status": "active",
        "vault_folder": None,
        "github_repo": None,
        "goal_id": None,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "device_id": "device-test",
        "revision": 1,
    }
    payload.update(overrides)
    return payload


def _project_envelope(**overrides) -> EventEnvelope:
    fields = dict(
        type="project.created",
        payload=project_payload(0),
        entity_refs=({"kind": "project", "id": "proj-0000"},),
    )
    fields.update(overrides)
    return make_envelope(0, **fields)


def competition_payload(index: int = 0, **overrides) -> dict:
    """A self-sufficient competition payload (ADR-014/EB-003) — the full
    07 §5.2 field set, matching
    `competition_service.competition_event_payload()`."""
    payload = {
        "id": f"comp-{index:04d}",
        "name": "USACO",
        "url": "https://usaco.org",
        "status": "discovered",
        "evaluation": None,
        "result": None,
        "project_id": None,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "device_id": "device-test",
        "revision": 1,
    }
    payload.update(overrides)
    return payload


def _competition_envelope(**overrides) -> EventEnvelope:
    fields = dict(
        type="competition.created",
        payload=competition_payload(0),
        entity_refs=({"kind": "competition", "id": "comp-0000"},),
    )
    fields.update(overrides)
    return make_envelope(0, **fields)


def milestone_payload(index: int = 0, **overrides) -> dict:
    """A self-sufficient milestone payload (ADR-015/EB-003) — the full
    07 §5.2 field set, matching
    `milestone_service.milestone_event_payload()`. `project_id` names a
    row the fixture's own `seed_sql` inserts first — `milestone.project_id`
    is `NOT NULL REFERENCES project(id)` (07 §5.2), unlike deadline's
    nullable competition_id/project_id, so "empty store" here means
    "empty except the FK this row structurally cannot exist without,"
    the same as it would for a real crash-recovery replay (the
    project.created event would already have landed first)."""
    payload = {
        "id": f"ms-{index:04d}",
        "project_id": "proj-for-milestone-fixture",
        "title": "Working prototype",
        "due": "2026-06-01T00:00:00+00:00",
        "status": "pending",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "device_id": "device-test",
        "revision": 1,
    }
    payload.update(overrides)
    return payload


def _milestone_envelope(**overrides) -> EventEnvelope:
    fields = dict(
        type="milestone.created",
        payload=milestone_payload(0),
        entity_refs=({"kind": "milestone", "id": "ms-0000"},),
    )
    fields.update(overrides)
    return make_envelope(0, **fields)


_MILESTONE_FIXTURE_PROJECT_SEED = (
    "INSERT INTO project (id, name, status, created_at, updated_at, "
    "device_id, revision) VALUES ('proj-for-milestone-fixture', 'Fixture "
    "project', 'active', '2026-01-01T00:00:00+00:00', "
    "'2026-01-01T00:00:00+00:00', 'device-test', 1)",
)


@dataclass(frozen=True)
class Fixture:
    """One recovery-grade type's proof: the envelope, and where its row
    should land. `seed_sql` runs before the envelope is applied — for
    types whose row cannot exist without a real FK parent already present
    (milestone.created; see its own payload builder's docstring)."""

    envelope: EventEnvelope
    table: str
    columns: str
    seed_sql: tuple[str, ...] = ()


# One fixture per recovery-grade type. A recovery-grade type absent from
# this map fails test_every_recovery_grade_type_has_a_fixture below.
_FIXTURES = {
    "task.created": Fixture(
        make_envelope(0, type="task.created"), "task", _TASK_COLUMNS
    ),
    "task.updated": Fixture(
        make_envelope(
            0,
            type="task.updated",
            payload=task_payload(
                0, status="done", revision=2, completed_at="2026-01-02T00:00:00+00:00"
            ),
        ),
        "task",
        _TASK_COLUMNS,
    ),
    "deadline.created": Fixture(_deadline_envelope(), "deadline", _DEADLINE_COLUMNS),
    # The `tracked → alerted` transition — the mutation ADR-004 registered
    # this type to carry, and the one a crash must not lose.
    "deadline.updated": Fixture(
        _deadline_envelope(
            type="deadline.updated",
            payload=deadline_payload(0, status="alerted", revision=2),
        ),
        "deadline",
        _DEADLINE_COLUMNS,
    ),
    "project.created": Fixture(_project_envelope(), "project", _PROJECT_COLUMNS),
    "competition.created": Fixture(
        _competition_envelope(), "competition", _COMPETITION_COLUMNS
    ),
    "milestone.created": Fixture(
        _milestone_envelope(),
        "milestone",
        _MILESTONE_COLUMNS,
        seed_sql=_MILESTONE_FIXTURE_PROJECT_SEED,
    ),
}


@pytest.fixture
def conn(tmp_path):
    connection = open_connection(tmp_path / "kang.db")
    apply_migrations(connection, MIGRATIONS_DIR, FakeClock())
    yield connection
    connection.close()


def test_every_recovery_grade_type_has_a_fixture():
    recovery_grade = {n for n, t in EVENT_TYPES.items() if t.recovery_grade}
    assert recovery_grade <= set(_FIXTURES), (
        "recovery-grade types without a payload-sufficiency fixture: "
        f"{recovery_grade - set(_FIXTURES)} (15 §16.2 — add one or the "
        "guarantee is unproven)"
    )


@pytest.mark.parametrize("type_name", sorted(_FIXTURES))
def test_payload_reconstructs_the_row_on_an_empty_store(conn, type_name):
    fixture = _FIXTURES[type_name]
    for sql in fixture.seed_sql:
        conn.execute(sql)
    envelope = fixture.envelope
    SqliteRecoveryApplier(conn).reapply(envelope)
    row = conn.execute(
        f"SELECT {fixture.columns} FROM {fixture.table} WHERE id = ?",
        (envelope.payload["id"],),
    ).fetchone()
    assert row is not None, f"{type_name}: no row reconstructed"
    names = fixture.columns.replace(" ", "").split(",")
    reconstructed = dict(zip(names, row))
    for field, value in envelope.payload.items():
        stored = reconstructed[field]
        if field == "lead_days":
            stored = json.loads(stored)  # JSON text in the column, list in the payload
        assert stored == value, f"{type_name}: field {field} diverged"


@pytest.mark.parametrize("type_name", sorted(_FIXTURES))
def test_reapplication_is_idempotent(conn, type_name):
    """EB-003: 're-application MUST be idempotent … re-applying a committed
    change is a no-op'. The crash window can deliver the same event twice."""
    fixture = _FIXTURES[type_name]
    for sql in fixture.seed_sql:
        conn.execute(sql)
    applier = SqliteRecoveryApplier(conn)
    assert applier.reapply(fixture.envelope).outcome == "applied"
    assert applier.reapply(fixture.envelope).outcome == "noop"
    count = conn.execute(
        f"SELECT COUNT(*) FROM {fixture.table} WHERE id = ?",
        (fixture.envelope.payload["id"],),
    ).fetchone()[0]
    assert count == 1
