"""audit.list / system.health — the System-domain Activity and Health
views (09_UI §12), added 2026-08-05.

The claim: both handlers are pure exposure of already-existing store
methods (`AuditService.records`/`.months`, `JobStore.list_jobs`/
`.consecutive_failures`, `KillSwitch.is_engaged`) — no filtering,
aggregation, or new domain logic of their own.
"""

from __future__ import annotations

from datetime import datetime, timezone

from kang.adapters.fakes.audit_log import FakeAuditLog
from kang.adapters.fakes.backup_service import FakeBackupService
from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.job_store import FakeJobStore, FakeKillSwitch
from kang.api.dispatch import HandlerContext
from kang.api.operations import make_audit_list_handler, make_system_health_handler
from kang.domain.ports.scheduler import Job
from kang.kernel.audit.service import AuditService

CONTEXT = HandlerContext(
    principal="kang", correlation_id="corr-1", trigger="cli", first_party=True
)


class TestAuditList:
    def test_defaults_to_the_clocks_current_month(self):
        clock = FakeClock()  # 2026-01-01
        audit = AuditService(FakeAuditLog(), clock)
        audit.record("kang", "task.create")
        handler = make_audit_list_handler(audit, clock)
        result = handler(CONTEXT, {})
        assert result["month"] == "2026-01"
        assert len(result["records"]) == 1

    def test_explicit_month_overrides_the_default(self):
        clock = FakeClock()
        audit = AuditService(FakeAuditLog(), clock)
        audit.record("kang", "task.create")
        handler = make_audit_list_handler(audit, clock)
        result = handler(CONTEXT, {"month": "2020-01"})
        assert result == {"month": "2020-01", "records": []}

    def test_record_fields_are_unfiltered(self):
        clock = FakeClock()
        audit = AuditService(FakeAuditLog(), clock)
        audit.record(
            "kang",
            "task.create",
            details={"task_id": "task-1"},
            correlation_id="corr-origin",
        )
        handler = make_audit_list_handler(audit, clock)
        (record,) = handler(CONTEXT, {})["records"]
        assert record["principal"] == "kang"
        assert record["action"] == "task.create"
        assert record["details"] == {"task_id": "task-1"}
        # The record's own stamped correlation_id, not the handler
        # call's — audit.list reads history, it doesn't relabel it.
        assert record["correlation_id"] == "corr-origin"


class TestSystemHealth:
    def test_empty_job_store_lists_nothing(self):
        handler = make_system_health_handler(
            FakeJobStore(), FakeKillSwitch(), FakeBackupService(), FakeClock()
        )
        assert handler(CONTEXT, {}) == {
            "jobs": [],
            "automation_engaged": False,
            "last_snapshot_at": None,
            "last_verify_at": None,
            "last_verify_ok": None,
            "external_backup_marker_at": None,
            "external_backup_stale": True,
        }

    def test_lists_a_registered_job_with_its_failure_count(self):
        job_store = FakeJobStore(clock=FakeClock())
        job_store.register_job(
            Job(
                id="morning_plan",
                name="morning_plan",
                schedule="cron:45 5 * * 1-6",
                catch_up="run_once_latest",
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        )
        handler = make_system_health_handler(
            job_store, FakeKillSwitch(), FakeBackupService(), FakeClock()
        )
        (job,) = handler(CONTEXT, {})["jobs"]
        assert job == {
            "id": "morning_plan",
            "name": "morning_plan",
            "schedule": "cron:45 5 * * 1-6",
            "catch_up": "run_once_latest",
            "enabled": True,
            "quarantined": False,
            "consecutive_failures": 0,
        }

    def test_reflects_the_kill_switch_state(self):
        kill_switch = FakeKillSwitch()
        kill_switch.engage("manual pause for testing")
        handler = make_system_health_handler(
            FakeJobStore(), kill_switch, FakeBackupService(), FakeClock()
        )
        assert handler(CONTEXT, {})["automation_engaged"] is True

    # ---- ADR-033: backup age + last restore-verification result --------

    def test_reflects_a_snapshot_with_no_verify_yet(self):
        backups = FakeBackupService()
        backups.take_snapshot("2026-09-12T02:30:00+00:00")
        handler = make_system_health_handler(
            FakeJobStore(), FakeKillSwitch(), backups, FakeClock()
        )
        result = handler(CONTEXT, {})
        assert result["last_snapshot_at"] == "2026-09-12T02:30:00+00:00"
        assert result["last_verify_at"] is None
        assert result["last_verify_ok"] is None

    def test_reflects_a_clean_verify(self):
        backups = FakeBackupService()
        backups.take_snapshot("2026-09-12T02:30:00+00:00")
        backups.verify_latest("2026-09-12T03:00:00+00:00")
        handler = make_system_health_handler(
            FakeJobStore(), FakeKillSwitch(), backups, FakeClock()
        )
        result = handler(CONTEXT, {})
        assert result["last_verify_at"] == "2026-09-12T03:00:00+00:00"
        assert result["last_verify_ok"] is True

    def test_reflects_a_failed_verify_not_just_integrity(self):
        """integrity_ok alone is not the claim — a broken read shape with
        a clean integrity check must still report last_verify_ok=False
        (ADR-032/033)."""
        from kang.domain.ports.backup import VerifyRecord

        backups = FakeBackupService()
        backups.take_snapshot("2026-09-12T02:30:00+00:00")
        backups.verify_result = VerifyRecord(
            verified_at="2026-09-12T03:00:00+00:00",
            snapshot="backups/daily/kang-20260912.db",
            integrity_ok=True,  # clean integrity...
            read_shapes_checked=("v_active_deadlines", "v_today_tasks"),
            read_shapes_not_built=("v_project_memory", "v_contested_records"),
            read_shape_errors=("v_today_tasks: broken",),  # ...but a broken shape
            live_row_counts={},
            snapshot_row_counts={},
            schema_version=17,
        )
        backups.verify_latest("2026-09-12T03:00:00+00:00")
        handler = make_system_health_handler(
            FakeJobStore(), FakeKillSwitch(), backups, FakeClock()
        )
        assert handler(CONTEXT, {})["last_verify_ok"] is False

    # ---- ADR-034: off-machine backup evidence ---------------------------

    def test_reflects_an_unconfigured_marker_as_stale(self):
        handler = make_system_health_handler(
            FakeJobStore(), FakeKillSwitch(), FakeBackupService(), FakeClock()
        )
        result = handler(CONTEXT, {})
        assert result["external_backup_marker_at"] is None
        assert result["external_backup_stale"] is True

    def test_reflects_a_fresh_marker_as_not_stale(self):
        backups = FakeBackupService()
        backups.external_marker_at = "2025-12-30T00:00:00+00:00"  # 2 days
        #   before FakeClock()'s default now (2026-01-01) — well inside
        #   the 7-day threshold.
        handler = make_system_health_handler(
            FakeJobStore(), FakeKillSwitch(), backups, FakeClock()
        )
        result = handler(CONTEXT, {})
        assert result["external_backup_marker_at"] == "2025-12-30T00:00:00+00:00"
        assert result["external_backup_stale"] is False

    def test_reflects_an_old_marker_as_stale(self):
        backups = FakeBackupService()
        backups.external_marker_at = "2025-01-01T00:00:00+00:00"  # nearly
        #   a year before FakeClock()'s default now — well past 7 days.
        handler = make_system_health_handler(
            FakeJobStore(), FakeKillSwitch(), backups, FakeClock()
        )
        assert handler(CONTEXT, {})["external_backup_stale"] is True
