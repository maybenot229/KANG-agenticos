"""AuditService: sole-writer attribution contract (SEC-006, SEC-013)."""

from __future__ import annotations

import pytest

from kang.adapters.fakes.audit_log import FakeAuditLog
from kang.adapters.fakes.clock import FakeClock
from kang.kernel.audit.service import AuditService, AuditWriteError
from kang.kernel.runtime.correlation import correlation_context


@pytest.fixture
def log() -> FakeAuditLog:
    return FakeAuditLog()


@pytest.fixture
def service(log) -> AuditService:
    return AuditService(log, FakeClock())


def test_record_stamps_time_from_the_injected_clock(service, log):
    record = service.record("kang", "task.create", details={"task_id": "task-0001"})
    assert record.entry.at == FakeClock().now().isoformat()
    assert list(log.records("2026-01")) == [record]


def test_anonymous_action_is_refused(service):
    with pytest.raises(AuditWriteError, match="principal"):
        service.record("  ", "task.create")


def test_actionless_entry_is_refused(service):
    with pytest.raises(AuditWriteError, match="action"):
        service.record("kang", "")


def test_correlation_id_defaults_to_the_ambient_context(service):
    with correlation_context("corr-9999"):
        record = service.record("agent:planner", "plan.generated")
    assert record.entry.correlation_id == "corr-9999"


def test_explicit_correlation_id_wins_over_context(service):
    with correlation_context("corr-ambient"):
        record = service.record("kang", "task.create", correlation_id="corr-explicit")
    assert record.entry.correlation_id == "corr-explicit"


def test_entries_chain_across_records(service, log):
    first = service.record("kang", "task.create")
    second = service.record("kang", "task.complete")
    assert second.prev_hash == first.entry_hash
    assert log.verify("2026-01").intact
