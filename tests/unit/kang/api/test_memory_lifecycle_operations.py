"""memory.update / .pin / .archive / .restore / .delete /
.restore_from_snapshot handlers (ADR-053) against fakes.

`memory.delete` is the gate half only here (mirrors `test_job_operations.py`
— it always raises `confirmation_required`, never deletes directly); the
real transactional effect, against a real connection, is proven in
`tests/integration/sqlite/test_memory_delete_transactional_effect.py`.
"""

from __future__ import annotations

import itertools

import pytest

from kang.adapters.fakes.audit_log import FakeAuditLog
from kang.adapters.fakes.backup_service import FakeBackupService
from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.delivery_store import FakeDeliveryStore
from kang.adapters.fakes.event_log import FakeEventLog
from kang.adapters.fakes.held_action_store import FakeHeldActionStore
from kang.adapters.fakes.memory_store import FakeMemoryStore
from kang.adapters.fakes.recovery import FakeRecoveryApplier
from kang.adapters.fakes.sleeper import FakeSleeper
from kang.api.dispatch import HandlerContext
from kang.api.errors import ApiError
from kang.api.operations import (
    ConfirmationDeps,
    MemoryLifecycleDeps,
    make_memory_lifecycle_handlers,
)
from kang.domain.ports.backup import MemoryRestoreOutcome
from kang.domain.ports.memory_store import MemoryRecord
from kang.kernel.audit.service import AuditService
from kang.kernel.bus.bus import EventBus
from kang.kernel.bus.delivery import Delivery
from kang.kernel.bus.reconciliation import Reconciliation
from kang.kernel.permissions.engine import PermissionEngine

DEVICE = "device-test"
KANG = HandlerContext("kang", "corr-k", "cli", first_party=True)


def record(**overrides) -> MemoryRecord:
    base = dict(
        id="mem-1",
        type="fact",
        status="active",
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


class Harness:
    def __init__(self):
        self.clock = FakeClock()
        ids = (f"id-{n:04d}" for n in itertools.count())
        self.new_id = lambda: next(ids)
        self.log = FakeEventLog(self.clock)
        self.audit_log = FakeAuditLog()
        self.audit = AuditService(self.audit_log, self.clock)
        engine = PermissionEngine({"kernel:memory": ("events.publish:kang",)})
        self.bus = EventBus(
            self.log,
            Delivery(
                self.log,
                FakeDeliveryStore(self.clock),
                self.audit,
                dead_letter_id=lambda: "dl",
                sleeper=FakeSleeper(),
            ),
            Reconciliation(self.log, FakeRecoveryApplier(), self.audit, self.clock),
            engine,
            self.audit,
        )
        self.memory = FakeMemoryStore()
        self.backups = FakeBackupService()
        self.held_actions = FakeHeldActionStore()
        self.deps = MemoryLifecycleDeps(
            bus=self.bus,
            memory=self.memory,
            backups=self.backups,
            confirmation=ConfirmationDeps(self.held_actions, self.clock, self.new_id),
            audit=self.audit,
            clock=self.clock,
            new_id=self.new_id,
            device_id=DEVICE,
        )
        self.handlers = make_memory_lifecycle_handlers(self.deps)

    def call(self, operation, context=KANG, **params):
        return self.handlers[operation](context, params)

    def updated_events(self):
        stored = self.log.read_from(0)
        return [s.envelope for s in stored if s.envelope.type == "memory.updated"]


@pytest.fixture
def h():
    return Harness()


# ---- memory.update ---------------------------------------------------------


class TestMemoryUpdate:
    def test_edits_content_and_reason_and_bumps_revision(self, h):
        h.memory.insert_record(record())
        result = h.call(
            "memory.update",
            id="mem-1",
            content="new content",
            reason="new reason",
            expected_revision=1,
        )
        assert result == {"id": "mem-1", "revision": 2}
        stored = h.memory.get("mem-1")
        assert stored.content == "new content"
        assert stored.reason == "new reason"
        assert stored.device_id == DEVICE

    def test_never_changes_type_tier_sensitivity_or_status(self, h):
        h.memory.insert_record(
            record(type="lesson", trust_tier=1, sensitivity="normal")
        )
        h.call(
            "memory.update",
            id="mem-1",
            content="x",
            reason="y",
            expected_revision=1,
        )
        stored = h.memory.get("mem-1")
        assert stored.type == "lesson"
        assert stored.trust_tier == 1
        assert stored.sensitivity == "normal"
        assert stored.status == "active"

    def test_publishes_memory_updated_with_the_full_row(self, h):
        h.memory.insert_record(record())
        h.call(
            "memory.update",
            id="mem-1",
            content="new content",
            reason="new reason",
            expected_revision=1,
        )
        events = h.updated_events()
        assert len(events) == 1
        assert events[0].payload["content"] == "new content"
        assert events[0].payload["revision"] == 2
        assert events[0].recovery_grade is True

    def test_refuses_a_stale_expected_revision(self, h):
        h.memory.insert_record(record())
        with pytest.raises(ApiError) as exc:
            h.call(
                "memory.update",
                id="mem-1",
                content="x",
                reason="y",
                expected_revision=5,
            )
        assert exc.value.code == "conflict"
        assert h.memory.get("mem-1") == record()  # untouched
        assert h.updated_events() == []

    def test_refuses_a_non_active_record(self, h):
        h.memory.insert_record(record(status="archived"))
        with pytest.raises(ApiError) as exc:
            h.call(
                "memory.update",
                id="mem-1",
                content="x",
                reason="y",
                expected_revision=1,
            )
        assert exc.value.code == "conflict"

    def test_refuses_an_unknown_id(self, h):
        with pytest.raises(ApiError) as exc:
            h.call(
                "memory.update",
                id="ghost",
                content="x",
                reason="y",
                expected_revision=1,
            )
        assert exc.value.code == "not_found"


# ---- memory.pin -------------------------------------------------------------


class TestMemoryPin:
    def test_sets_pinned_and_bumps_revision(self, h):
        h.memory.insert_record(record(pinned=False))
        result = h.call("memory.pin", id="mem-1", pinned=True)
        assert result == {"id": "mem-1", "revision": 2, "pinned": True}

    def test_is_idempotent_in_effect(self, h):
        h.memory.insert_record(record(pinned=True))
        result = h.call("memory.pin", id="mem-1", pinned=True)
        assert result["pinned"] is True

    def test_refuses_an_unknown_id(self, h):
        with pytest.raises(ApiError) as exc:
            h.call("memory.pin", id="ghost", pinned=True)
        assert exc.value.code == "not_found"


# ---- memory.archive / memory.restore ----------------------------------------


class TestMemoryArchiveRestore:
    def test_archive_moves_active_to_archived(self, h):
        h.memory.insert_record(record(status="active"))
        result = h.call("memory.archive", id="mem-1")
        assert result == {"id": "mem-1", "revision": 2, "status": "archived"}

    def test_archive_refuses_an_already_archived_record(self, h):
        h.memory.insert_record(record(status="archived"))
        with pytest.raises(ApiError) as exc:
            h.call("memory.archive", id="mem-1")
        assert exc.value.code == "conflict"

    def test_restore_moves_archived_to_active(self, h):
        h.memory.insert_record(record(status="archived"))
        result = h.call("memory.restore", id="mem-1")
        assert result == {"id": "mem-1", "revision": 2, "status": "active"}

    def test_restore_refuses_an_active_record(self, h):
        h.memory.insert_record(record(status="active"))
        with pytest.raises(ApiError) as exc:
            h.call("memory.restore", id="mem-1")
        assert exc.value.code == "conflict"


# ---- memory.delete (the gate half only) -------------------------------------


class TestMemoryDelete:
    def test_always_raises_confirmation_required_never_deletes_directly(self, h):
        h.memory.insert_record(record(status="archived"))
        with pytest.raises(ApiError) as exc:
            h.call("memory.delete", id="mem-1", reason="no longer needed")
        assert exc.value.code == "confirmation_required"
        assert h.memory.get("mem-1") is not None  # untouched — no effect ran

    def test_the_held_action_carries_both_reversibility_facts(self, h):
        h.memory.insert_record(record(status="archived"))
        with pytest.raises(ApiError) as exc:
            h.call("memory.delete", id="mem-1", reason="no longer needed")
        held = h.held_actions.get(exc.value.details["id"])
        assert held.operation == "memory.delete"
        assert held.params == {"record_id": "mem-1", "deleted_by": "kang"}
        assert "30 days" in held.reversibility
        assert "twelve months" in held.reversibility
        assert "not destruction from your backups" in held.reversibility

    def test_the_action_text_names_the_record_and_quotes_its_content(self, h):
        h.memory.insert_record(record(status="archived", content="a secret plan"))
        with pytest.raises(ApiError) as exc:
            h.call("memory.delete", id="mem-1", reason="no longer needed")
        held = h.held_actions.get(exc.value.details["id"])
        assert "mem-1" in held.action
        assert "a secret plan" in held.action

    def test_refuses_an_active_record_no_held_action_created(self, h):
        """M-002 has no `active -> deleted` edge (ADR-053 D3) — a safety
        property, refused before any confirmation is even offered."""
        h.memory.insert_record(record(status="active"))
        with pytest.raises(ApiError) as exc:
            h.call("memory.delete", id="mem-1", reason="testing")
        assert exc.value.code == "conflict"
        assert h.held_actions.pending() == []

    def test_refuses_an_unknown_id(self, h):
        with pytest.raises(ApiError) as exc:
            h.call("memory.delete", id="ghost", reason="testing")
        assert exc.value.code == "not_found"
        assert h.held_actions.pending() == []


# ---- memory.restore_from_snapshot -------------------------------------------


class TestMemoryRestoreFromSnapshot:
    def test_restored_outcome_returns_id_revision_and_snapshot(self, h):
        h.backups.restore_result = MemoryRestoreOutcome(
            outcome="restored", id="mem-1", revision=4, snapshot="daily/kang-x.db"
        )
        result = h.call("memory.restore_from_snapshot", id="mem-1")
        assert result == {"id": "mem-1", "revision": 4, "snapshot": "daily/kang-x.db"}
        assert h.backups.restore_calls == ["mem-1"]

    def test_conflict_outcome_is_an_api_conflict(self, h):
        h.backups.restore_result = MemoryRestoreOutcome(outcome="conflict", id="mem-1")
        with pytest.raises(ApiError) as exc:
            h.call("memory.restore_from_snapshot", id="mem-1")
        assert exc.value.code == "conflict"

    def test_not_found_outcome_is_an_api_not_found(self, h):
        h.backups.restore_result = MemoryRestoreOutcome(outcome="not_found", id="mem-1")
        with pytest.raises(ApiError) as exc:
            h.call("memory.restore_from_snapshot", id="mem-1")
        assert exc.value.code == "not_found"

    def test_never_publishes_memory_updated(self, h):
        h.backups.restore_result = MemoryRestoreOutcome(
            outcome="restored", id="mem-1", revision=4, snapshot="daily/kang-x.db"
        )
        h.call("memory.restore_from_snapshot", id="mem-1")
        assert h.updated_events() == []
