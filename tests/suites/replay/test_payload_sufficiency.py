"""Payload-sufficiency suite (15 §16.2 / EB-003) — a standing obligation:
for every recovery-grade event type, applying the fixture event to an EMPTY
store yields the recorded row. A recovery-grade type without this proof
fails CI (a thinned payload silently breaks crash recovery).

This test is registry-driven: it iterates the event registry, so a future
recovery-grade type with no fixture here fails loudly rather than silently
skipping the guarantee.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.migrations import apply_migrations
from kang.adapters.sqlite.recovery import SqliteRecoveryApplier
from kang.kernel.bus.event_registry import EVENT_TYPES
from tests.fixtures.event_log_contract import make_envelope, task_payload

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"

# One fixture envelope per recovery-grade type. A recovery-grade type absent
# from this map fails test_every_recovery_grade_type_has_a_fixture below.
_FIXTURES = {
    "task.created": make_envelope(0, type="task.created"),
    "task.updated": make_envelope(
        0,
        type="task.updated",
        payload=task_payload(
            0, status="done", revision=2, completed_at="2026-01-02T00:00:00+00:00"
        ),
    ),
}

_TASK_COLUMNS = (
    "id, project_id, title, notes, status, priority, due, plan_date, "
    "estimate_min, actual_min, completed_at, created_at, updated_at, "
    "device_id, revision"
)


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
    envelope = _FIXTURES[type_name]
    SqliteRecoveryApplier(conn).reapply(envelope)
    row = conn.execute(
        f"SELECT {_TASK_COLUMNS} FROM task WHERE id = ?", (envelope.payload["id"],)
    ).fetchone()
    assert row is not None
    reconstructed = dict(zip(_TASK_COLUMNS.replace(" ", "").split(","), row))
    for field, value in envelope.payload.items():
        assert reconstructed[field] == value, f"{type_name}: field {field} diverged"
