"""backup.snapshot / backup.verify / backup.offsite_check handlers
(ADR-031, ADR-032, ADR-034).

The claim: each handler is thin (12 §2) — it resolves the clock, calls the
BackupService once, returns the port's own fields, and maps a typed
refusal to a loud API-006 code. No policy lives here.

Verify's own claim, distinct from snapshot's: a FAILED check is a normal
returned response (`integrity_ok=False`), never an `ApiError` — only "no
snapshot to verify" raises. Collapsing a failed check into an exception
would hide the one finding this operation exists to surface.

Offsite check's own claim: it publishes `backup.offsite_stale` only when
stale, and never raises at all — an unconfigured marker is a normal,
honest result, not a refusal.
"""

from __future__ import annotations

import itertools

import pytest

from kang.adapters.fakes.audit_log import FakeAuditLog
from kang.adapters.fakes.backup_service import FakeBackupService
from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.delivery_store import FakeDeliveryStore
from kang.adapters.fakes.event_log import FakeEventLog
from kang.adapters.fakes.recovery import FakeRecoveryApplier
from kang.adapters.fakes.sleeper import FakeSleeper
from kang.api.dispatch import HandlerContext
from kang.api.errors import ApiError
from kang.api.operations import (
    make_backup_offsite_check_handler,
    make_backup_snapshot_handler,
    make_backup_verify_handler,
)
from kang.domain.ports.backup import VerifyRecord
from kang.kernel.audit.service import AuditService
from kang.kernel.bus.bus import EventBus
from kang.kernel.bus.delivery import Delivery
from kang.kernel.bus.reconciliation import Reconciliation
from kang.kernel.permissions.engine import PermissionEngine

DEVICE = "device-test"

CONTEXT = HandlerContext(
    principal="kernel:scheduler",
    correlation_id="corr-job",
    trigger="kernel:scheduler",
    first_party=False,
)


def _handler(service, clock):
    return make_backup_snapshot_handler(service, clock)


def test_snapshot_returns_the_manifest_fields():
    service, clock = FakeBackupService(), FakeClock()
    result = _handler(service, clock)(CONTEXT, {})
    assert result["integrity_ok"] is True
    assert result["database"].endswith(".db")
    assert result["eventlog"].endswith(".db")
    assert set(result) == {
        "database",
        "eventlog",
        "audit",
        "bytes_total",
        "integrity_ok",
        "schema_version",
        "promoted_monthly",
        "pruned",
    }


def test_the_handler_uses_the_injected_clock_not_wall_time():
    """11 §25 — the snapshot's date comes from the Clock port, so a
    replayed slot is deterministic."""
    service, clock = FakeBackupService(), FakeClock()
    _handler(service, clock)(CONTEXT, {})
    assert service.taken[0].taken_at == clock.now().isoformat()


def test_a_refused_snapshot_is_a_loud_internal_error():
    """05_AGENTS Appendix A's backup row: "alert on any failure — no
    silent skip, ever." A BackupError must never degrade to a success."""
    service, clock = FakeBackupService(), FakeClock()
    service.fail_with = "integrity_check failed; refusing to snapshot"
    with pytest.raises(ApiError) as exc:
        _handler(service, clock)(CONTEXT, {})
    assert exc.value.code == "internal"
    assert "refused" in exc.value.message


def test_a_refusal_records_no_snapshot():
    service, clock = FakeBackupService(), FakeClock()
    service.fail_with = "suspect state"
    with pytest.raises(ApiError):
        _handler(service, clock)(CONTEXT, {})
    assert service.taken == []


# ---- ADR-032: backup.verify ---------------------------------------------


def _verify_handler(service, clock):
    return make_backup_verify_handler(service, clock)


def test_verify_returns_the_record_fields():
    service, clock = FakeBackupService(), FakeClock()
    result = _verify_handler(service, clock)(CONTEXT, {})
    assert set(result) == {
        "snapshot",
        "integrity_ok",
        "read_shapes_checked",
        "read_shapes_not_built",
        "read_shape_errors",
        "live_row_counts",
        "snapshot_row_counts",
        "schema_version",
    }


def test_a_failed_check_is_a_normal_response_not_a_raise():
    """The central claim of ADR-032 D4, at the handler seam: a failed
    integrity check must reach the caller as data, not disappear inside
    an exception nobody without try/except would see."""
    service, clock = FakeBackupService(), FakeClock()
    service.verify_result = VerifyRecord(
        verified_at=clock.now().isoformat(),
        snapshot="backups/daily/kang-20260101.db",
        integrity_ok=False,
        read_shapes_checked=("v_active_deadlines", "v_today_tasks"),
        read_shapes_not_built=("v_project_memory", "v_contested_records"),
        read_shape_errors=("v_today_tasks: database disk image is malformed",),
        live_row_counts={},
        snapshot_row_counts={},
        schema_version=17,
    )
    result = _verify_handler(service, clock)(CONTEXT, {})  # does NOT raise
    assert result["integrity_ok"] is False
    assert result["read_shape_errors"] != []


def test_no_snapshot_to_verify_is_a_loud_internal_error():
    """The ONLY case that raises — a structurally different condition
    from a failed check (nothing exists to open at all)."""
    service, clock = FakeBackupService(), FakeClock()
    service.verify_fail_with = "no daily snapshot exists to verify"
    with pytest.raises(ApiError) as exc:
        _verify_handler(service, clock)(CONTEXT, {})
    assert exc.value.code == "internal"
    assert "refused" in exc.value.message


def test_the_verify_handler_also_uses_the_injected_clock():
    service, clock = FakeBackupService(), FakeClock()
    _verify_handler(service, clock)(CONTEXT, {})
    assert service.verified[0].verified_at == clock.now().isoformat()


# ---- ADR-034: backup.offsite_check ---------------------------------------


@pytest.fixture
def offsite_wiring():
    clock = FakeClock()
    ids = (f"id-{n:04d}" for n in itertools.count())
    event_log = FakeEventLog(clock)
    audit = AuditService(FakeAuditLog(), clock)
    bus = EventBus(
        event_log,
        Delivery(
            event_log,
            FakeDeliveryStore(clock),
            audit,
            dead_letter_id=lambda: "dl",
            sleeper=FakeSleeper(),
        ),
        Reconciliation(event_log, FakeRecoveryApplier(), audit, clock),
        PermissionEngine({"kernel:backups": ("events.publish:kang",)}),
        audit,
    )
    return {
        "bus": bus,
        "backups": FakeBackupService(),
        "clock": clock,
        "new_id": lambda: next(ids),
        "log": event_log,
    }


def _offsite_check(wiring):
    handler = make_backup_offsite_check_handler(
        wiring["backups"], wiring["bus"], wiring["clock"], wiring["new_id"], DEVICE
    )
    return handler(CONTEXT, {})


def _published(wiring) -> list[str]:
    return [s.envelope.type for s in wiring["log"].read_from(0)]


def test_an_unconfigured_marker_is_reported_and_announced(offsite_wiring):
    result = _offsite_check(offsite_wiring)
    assert result == {"last_marker_at": None, "stale": True}
    assert _published(offsite_wiring) == ["backup.offsite_stale"]


def test_a_fresh_marker_is_reported_and_nothing_is_announced(offsite_wiring):
    offsite_wiring["backups"].external_marker_at = (
        offsite_wiring["clock"].now().isoformat()
    )
    result = _offsite_check(offsite_wiring)
    assert result["stale"] is False
    # Part XII.5's own framing: silence is the healthy state.
    assert _published(offsite_wiring) == []


def test_the_stale_event_carries_the_marker_and_no_causation(offsite_wiring):
    _offsite_check(offsite_wiring)
    (stored,) = offsite_wiring["log"].read_from(0)
    assert stored.envelope.payload["last_marker_at"] is None
    assert stored.envelope.causation_id is None  # a genuine root cause
    assert stored.envelope.entity_refs == ({"kind": "backup", "id": "offsite"},)
    assert stored.envelope.recovery_grade is False


def test_the_offsite_handler_also_uses_the_injected_clock(offsite_wiring):
    """11 §25 — the check compares against the Clock port, not wall time."""
    offsite_wiring["backups"].external_marker_at = "2020-01-01T00:00:00+00:00"
    result = _offsite_check(offsite_wiring)
    # Far older than 7 days before FakeClock()'s 2026-01-01 default — stale.
    assert result["stale"] is True
