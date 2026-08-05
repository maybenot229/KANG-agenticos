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
        handler = make_system_health_handler(FakeJobStore(), FakeKillSwitch())
        assert handler(CONTEXT, {}) == {"jobs": [], "automation_engaged": False}

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
        handler = make_system_health_handler(job_store, FakeKillSwitch())
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
        handler = make_system_health_handler(FakeJobStore(), kill_switch)
        assert handler(CONTEXT, {})["automation_engaged"] is True
