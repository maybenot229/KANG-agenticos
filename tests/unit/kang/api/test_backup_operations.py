"""backup.snapshot handler (ADR-031).

The claim: the handler is thin (12 §2) — it resolves the clock, calls the
BackupService once, returns the manifest fields, and maps the port's typed
refusal to a loud API-006 code. No policy lives here.
"""

from __future__ import annotations

import pytest

from kang.adapters.fakes.backup_service import FakeBackupService
from kang.adapters.fakes.clock import FakeClock
from kang.api.dispatch import HandlerContext
from kang.api.errors import ApiError
from kang.api.operations import make_backup_snapshot_handler

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
