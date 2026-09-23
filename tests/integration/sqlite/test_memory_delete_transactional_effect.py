"""memory.delete's real transactional effect (ADR-053 D4), against a real
SQLite connection — the one irreversible operation in the memory system.

The claim under test: the approve-flip, the row deletion (cascading
`memory_revision`, firing the FTS and change-capture delete triggers), and
the tombstone insert genuinely share ONE transaction with the held
action's approve/mark-executed writes — a forced failure mid-sequence
leaves the record, its tombstone, and the held action exactly as if
nothing had been attempted.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kang.adapters.fakes.audit_log import FakeAuditLog
from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.held_action_store import SqliteHeldActionStore
from kang.adapters.sqlite.memory_store import SqliteMemoryStore
from kang.adapters.sqlite.migrations import apply_migrations
from kang.api.dispatch import HandlerContext
from kang.api.errors import ApiError
from kang.api.operations.held_action_ops import make_held_action_approve_handler
from kang.api.operations.memory_lifecycle_ops import make_memory_delete_effect
from kang.domain.ports.held_action import HeldAction
from kang.domain.ports.memory_store import MemoryRecord
from kang.kernel.audit.service import AuditService

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"
ANCHOR = datetime(2026, 1, 1, tzinfo=timezone.utc)
CONTEXT = HandlerContext(
    principal="kang", correlation_id="corr-1", trigger="cli", first_party=True
)


def _record(**overrides) -> MemoryRecord:
    base = dict(
        id="mem-1",
        type="fact",
        status="archived",
        content="School term ends June 12",
        trust_tier=1,
        confidence=1.0,
        sensitivity="normal",
        source_kind="stated",
        source_detail="conversation",
        reason="Kang said so",
        created_by="kang",
        created_at="2026-09-21T10:00:00+00:00",
        updated_at="2026-09-21T10:00:00+00:00",
        device_id="dev-seed",
        revision=1,
    )
    base.update(overrides)
    return MemoryRecord(**base)


@pytest.fixture
def rig(tmp_path):
    conn = open_connection(tmp_path / "kang.db")
    clock = FakeClock()
    apply_migrations(conn, MIGRATIONS_DIR, clock)
    memory = SqliteMemoryStore(conn)
    audit_log = FakeAuditLog()
    audit = AuditService(audit_log, clock)
    return {
        "conn": conn,
        "clock": clock,
        "held_actions": SqliteHeldActionStore(conn),
        "memory": memory,
        "audit": audit,
        "audit_log": audit_log,
    }


def _seed_pending(rig, record_id="mem-1") -> HeldAction:
    now = rig["clock"].now()
    held = HeldAction(
        id="held-0000",
        operation="memory.delete",
        action=f"Delete memory record {record_id}: 'School term ends June 12'",
        principal="kang",
        reason="no longer needed",
        reversibility="30 days ... twelve months ... not destruction from your backups",
        correlation_id="corr-origin",
        created_at=now.isoformat(),
        expires_at=(now + timedelta(hours=24)).isoformat(),
        params={"record_id": record_id, "deleted_by": "kang"},
    )
    rig["held_actions"].create(held)
    return held


def _effects(rig):
    return {
        "memory.delete": make_memory_delete_effect(
            rig["memory"], rig["audit"], rig["clock"]
        )
    }


def test_approve_deletes_the_row_and_tombstones_it_in_one_transaction(rig):
    rig["memory"].insert_record(_record())
    _seed_pending(rig)
    handler = make_held_action_approve_handler(
        rig["held_actions"], rig["clock"], rig["conn"], _effects(rig)
    )
    result = handler(CONTEXT, {"id": "held-0000"})
    assert result == {"id": "held-0000", "status": "executed"}
    assert rig["held_actions"].get("held-0000").status == "executed"
    assert rig["memory"].get("mem-1") is None

    tombstone = (
        rig["conn"]
        .execute(
            "SELECT entity, deleted_by, policy_ref FROM tombstone WHERE id = 'mem-1'"
        )
        .fetchone()
    )
    assert tombstone == ("memory_record", "kang", "kang:explicit")

    delete_ops = (
        rig["conn"]
        .execute(
            "SELECT COUNT(*) FROM change_log WHERE entity = 'memory_record' "
            "AND entity_id = 'mem-1' AND op = 'delete'"
        )
        .fetchone()[0]
    )
    assert delete_ops == 1


def test_the_revisions_and_fts_entry_are_gone_too(rig):
    rig["memory"].insert_record(_record())
    rig["conn"].execute(
        "INSERT INTO memory_revision (record_id, revision, content, edited_by, "
        "edited_at, device_id) VALUES ('mem-1', 1, 'old', 'kang', "
        "'2026-09-20T00:00:00+00:00', 'dev-1')"
    )
    rig["conn"].commit()
    _seed_pending(rig)
    handler = make_held_action_approve_handler(
        rig["held_actions"], rig["clock"], rig["conn"], _effects(rig)
    )
    handler(CONTEXT, {"id": "held-0000"})

    revisions = (
        rig["conn"]
        .execute("SELECT COUNT(*) FROM memory_revision WHERE record_id = 'mem-1'")
        .fetchone()[0]
    )
    assert revisions == 0  # ON DELETE CASCADE
    fts_hits = (
        rig["conn"]
        .execute("SELECT COUNT(*) FROM fts_memory WHERE fts_memory MATCH 'term'")
        .fetchone()[0]
    )
    assert fts_hits == 0


def test_the_audit_log_carries_the_policy_citation(rig):
    rig["memory"].insert_record(_record())
    _seed_pending(rig)
    handler = make_held_action_approve_handler(
        rig["held_actions"], rig["clock"], rig["conn"], _effects(rig)
    )
    handler(CONTEXT, {"id": "held-0000"})
    entries = [
        r.entry
        for m in rig["audit_log"].months()
        for r in rig["audit_log"].records(m)
        if r.entry.action == "memory.deleted"
    ]
    assert len(entries) == 1
    assert entries[0].details == {"id": "mem-1", "policy_ref": "kang:explicit"}
    assert entries[0].principal == "kang"


def test_active_to_deleted_is_refused_and_rolls_back(rig):
    """M-002 has no `active -> deleted` edge — the store's own guard
    inside the effect refuses it, and the whole transaction (approve-flip
    included) rolls back with it."""
    rig["memory"].insert_record(_record(status="active"))
    _seed_pending(rig)
    handler = make_held_action_approve_handler(
        rig["held_actions"], rig["clock"], rig["conn"], _effects(rig)
    )
    with pytest.raises(ApiError) as exc:
        handler(CONTEXT, {"id": "held-0000"})
    assert exc.value.code == "conflict"
    assert rig["held_actions"].get("held-0000").status == "pending"
    assert rig["memory"].get("mem-1") is not None
    assert rig["conn"].in_transaction is False


def test_a_failing_effect_rolls_back_the_approve_flip_too(rig):
    rig["memory"].insert_record(_record())
    _seed_pending(rig)

    def _boom(params):
        raise RuntimeError("adapter exploded")

    handler = make_held_action_approve_handler(
        rig["held_actions"], rig["clock"], rig["conn"], {"memory.delete": _boom}
    )
    with pytest.raises(RuntimeError):
        handler(CONTEXT, {"id": "held-0000"})
    assert rig["held_actions"].get("held-0000").status == "pending"
    assert rig["memory"].get("mem-1") is not None
    assert rig["conn"].in_transaction is False
