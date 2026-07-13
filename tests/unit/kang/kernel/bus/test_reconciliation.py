"""The caged reconciliation module (§4) — unit-tested against fakes.

Recovery-grade pending events are re-applied idempotently and confirmed;
non-recovery-grade pending events are confirmed if their referenced state
exists, else orphaned (never delivered, never deleted). The window is
reported to audit.
"""

from __future__ import annotations

import pytest

from kang.adapters.fakes.audit_log import FakeAuditLog
from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.event_log import FakeEventLog
from kang.adapters.fakes.recovery import FakeRecoveryApplier
from kang.kernel.audit.service import AuditService
from kang.kernel.bus.reconciliation import Reconciliation
from tests.fixtures.event_log_contract import make_envelope


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def event_log(clock) -> FakeEventLog:
    return FakeEventLog(clock)


@pytest.fixture
def applier() -> FakeRecoveryApplier:
    return FakeRecoveryApplier()


@pytest.fixture
def audit_log() -> FakeAuditLog:
    return FakeAuditLog()


@pytest.fixture
def reconciliation(event_log, applier, audit_log, clock) -> Reconciliation:
    return Reconciliation(event_log, applier, AuditService(audit_log, clock), clock)


def test_empty_pending_window_is_a_clean_report(reconciliation):
    report = reconciliation.run()
    assert (report.window, report.reapplied, report.confirmed, report.orphaned) == (
        0,
        0,
        0,
        0,
    )


def test_recovery_grade_ghost_event_is_reapplied_and_confirmed(
    reconciliation, event_log, applier
):
    event_log.append(make_envelope(0))  # recovery-grade task.created, pending
    report = reconciliation.run()
    assert report.reapplied == 1
    assert event_log.pending() == []
    assert applier.rows["task-0000"]["title"] == "prove the log"


def test_reapplication_is_idempotent_across_two_runs(reconciliation, event_log):
    event_log.append(make_envelope(0))
    reconciliation.run()
    # nothing pending now; a second run is a clean no-op
    second = reconciliation.run()
    assert second.window == 0


def test_non_recovery_event_with_present_state_is_confirmed(
    reconciliation, event_log, applier
):
    applier.rows["task-0000"] = {"id": "task-0000", "revision": 1}
    event_log.append(
        make_envelope(
            0,
            type="task.updated",  # any registered shape; here used non-recovery
            recovery_grade=False,
            payload={"note": "informational"},
            entity_refs=({"kind": "task", "id": "task-0000"},),
        )
    )
    report = reconciliation.run()
    assert report.confirmed == 1
    assert report.orphaned == 0


def test_non_recovery_event_with_absent_state_is_orphaned(reconciliation, event_log):
    seq = event_log.append(
        make_envelope(
            0,
            recovery_grade=False,
            payload={"note": "informational"},
            entity_refs=({"kind": "task", "id": "task-absent"},),
        )
    )
    report = reconciliation.run()
    assert report.orphaned == 1
    # orphaned: never deleted — still present, marked
    (stored,) = [e for e in event_log.read_from(0) if e.seq == seq]
    assert stored.state == "orphaned"


def test_window_is_reported_to_audit(reconciliation, event_log, audit_log):
    event_log.append(make_envelope(0))
    reconciliation.run()
    (record,) = list(audit_log.records(FakeClock().now().isoformat()[:7]))
    assert record.entry.action == "reconciliation.completed"
    assert record.entry.principal == "kernel:bus"
    assert record.entry.details["reapplied"] == 1
