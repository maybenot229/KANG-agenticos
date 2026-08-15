"""morning_plan as a registered job — ADR-006 end to end, real wired Core.

Proves the three things registration is supposed to buy:
  1. the job exists with Kang's REAL cron schedule, from config not code;
  2. a due slot dispatches `plan.generate` through the ordinary pipeline,
     so the run is invocation-recorded and explainable;
  3. catch-up after simulated downtime honours `run_once_latest` — one plan,
     not one per missed morning.

And the security property that matters most: a job dispatches with
`first_party=False`, so automation is structurally unable to approve a held
action (ADR-002/ADR-006, SEC-003).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from kang.adapters.sqlite.connection import open_connection
from kang.api.dispatch import ApiRequest
from kang.kernel.runtime.composition import build_core
from kang.kernel.runtime.scheduler_wiring import JOB_OPERATIONS, MORNING_PLAN_JOB

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULTS = REPO_ROOT / "config" / "defaults"
KUCHING = ZoneInfo("Asia/Kuching")


def _seed_config(kang_home: Path) -> None:
    config = kang_home / "config"
    config.mkdir(parents=True, exist_ok=True)
    for name in ("permissions.toml", "kang.toml"):
        (config / name).write_text(
            (DEFAULTS / name).read_text(encoding="utf-8"), encoding="utf-8"
        )


@pytest.fixture
def core(tmp_path):
    _seed_config(tmp_path)
    built = build_core(tmp_path)
    yield built, tmp_path
    built.close()


def _call(core, operation, params, key):
    session = core.mint_first_party_session()
    response = core.dispatcher.dispatch(
        ApiRequest(operation, params, session.token, idempotency_key=key)
    )
    assert response["ok"] is True, response
    return response["result"]


def _simulate_downtime(kang_home: Path, days: int) -> None:
    """Backdate the job's creation so `days` of morning slots have elapsed.

    A freshly-registered job has NO missed slots — its catch-up baseline is
    its own creation time, so its first fire is the next occurrence, not an
    immediate one. That is correct (registering a job must not retroactively
    fire it), and it means downtime has to be simulated to exercise catch-up
    at all.
    """
    conn = open_connection(kang_home / "kang.db")
    try:
        past = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        conn.execute(
            "UPDATE job SET created_at = ? WHERE id = ?", (past, MORNING_PLAN_JOB)
        )
        conn.commit()
    finally:
        conn.close()


def _job_row(kang_home: Path):
    conn = open_connection(kang_home / "kang.db")
    try:
        return conn.execute(
            "SELECT id, name, schedule, catch_up, enabled, quarantined "
            "FROM job WHERE id = ?",
            (MORNING_PLAN_JOB,),
        ).fetchone()
    finally:
        conn.close()


class TestRegistration:
    def test_the_job_exists_after_boot(self, core):
        _, home = core
        row = _job_row(home)
        assert row is not None, "morning_plan was never registered"
        assert row[1] == MORNING_PLAN_JOB
        assert row[4] == 1 and row[5] == 0  # enabled, not quarantined

    def test_the_schedule_comes_from_config_not_code(self, core):
        _, home = core
        schedule = _job_row(home)[2]
        # 05:45 Mon-Sat and 06:45 Sun, exactly as kang.toml seeds them
        assert schedule.startswith("cron:")
        assert "45 5 * * 1-6" in schedule
        assert "45 6 * * 0" in schedule

    def test_catch_up_policy_is_run_once_latest(self, core):
        """One missed morning must not become five plans."""
        _, home = core
        assert _job_row(home)[3] == "run_once_latest"

    def test_registration_is_idempotent_across_reboots(self, tmp_path):
        _seed_config(tmp_path)
        for _ in range(2):
            built = build_core(tmp_path)
            built.close()
        conn = open_connection(tmp_path / "kang.db")
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM job WHERE id = ?", (MORNING_PLAN_JOB,)
            ).fetchone()[0]
        finally:
            conn.close()
        assert count == 1

    def test_the_job_maps_to_a_real_registered_operation(self):
        from kang.api.registry import operation

        target = JOB_OPERATIONS[MORNING_PLAN_JOB]
        assert operation(target) is not None, f"{target} is not in the registry"


class TestDispatch:
    def test_a_due_slot_runs_the_plan_and_records_an_invocation(self, core):
        built, home = core
        _call(built, "task.create", {"title": "Olympiad drill", "priority": 1}, "t1")
        _simulate_downtime(home, days=3)

        report = built.scheduler.catch_up()
        assert report.paused is False
        assert report.ran >= 1, report

        conn = open_connection(home / "kang.db")
        try:
            # the run was recorded against the job...
            outcomes = [
                row[0]
                for row in conn.execute(
                    "SELECT outcome FROM job_run WHERE job_id = ?", (MORNING_PLAN_JOB,)
                )
            ]
            # ...and the dispatch left an invocation, so it is explainable
            invoked = conn.execute(
                "SELECT COUNT(*) FROM invocation WHERE operation = 'plan.generate'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert "ok" in outcomes
        assert invoked >= 1

    def test_the_job_dispatches_as_kernel_scheduler_not_as_kang(self, core):
        built, home = core
        _call(built, "task.create", {"title": "Olympiad drill", "priority": 1}, "t1")
        _simulate_downtime(home, days=3)
        built.scheduler.catch_up()
        conn = open_connection(home / "kang.db")
        try:
            principals = {
                row[0]
                for row in conn.execute(
                    "SELECT principal FROM invocation WHERE operation = 'plan.generate'"
                )
            }
        finally:
            conn.close()
        assert principals == {"kernel:scheduler"}

    def test_a_job_session_is_never_first_party(self, core):
        """The security property: automation cannot approve held actions,
        because first-party means "arrived through Kang's own UI" (ADR-002).
        A regression here would silently let jobs approve their own
        consequences (SEC-003)."""
        built, home = core
        _call(built, "task.create", {"title": "Olympiad drill", "priority": 1}, "t1")
        _simulate_downtime(home, days=3)
        built.scheduler.catch_up()
        conn = open_connection(home / "kang.db")
        try:
            rows = conn.execute(
                "SELECT first_party FROM session WHERE principal = 'kernel:scheduler'"
            ).fetchall()
        finally:
            conn.close()
        assert rows, "the scheduler never minted a session"
        assert all(row[0] == 0 for row in rows)


class TestCatchUp:
    def test_downtime_produces_one_plan_not_one_per_missed_morning(self, core):
        """`run_once_latest` (D014's own example: "morning plan: generate
        today's, skip missed days"), proven against the real job."""
        built, home = core
        _call(built, "task.create", {"title": "Olympiad drill", "priority": 1}, "t1")
        _simulate_downtime(home, days=5)  # five missed mornings

        # run_once_latest collapses them into ONE run, not five.
        first = built.scheduler.catch_up()
        assert first.ran == 1, first

        # A second pass with no new slots runs nothing — the baseline moved.
        second = built.scheduler.catch_up()
        assert second.ran == 0, second

    def test_a_freshly_registered_job_does_not_fire_retroactively(self, core):
        """Registering a job must not act as if it had always existed."""
        built, _ = core
        assert built.scheduler.catch_up().ran == 0

    def test_the_kill_switch_pauses_the_morning_plan(self, core):
        """D013: one command pauses all automation, including this job."""
        built, home = core
        conn = open_connection(home / "kang.db")
        try:
            from kang.adapters.sqlite.job_store import SqliteKillSwitch

            class _Now:
                def now(self):
                    return datetime(2026, 3, 2, tzinfo=timezone.utc)

            SqliteKillSwitch(conn, _Now()).engage("test")
        finally:
            conn.close()
        report = built.scheduler.catch_up()
        assert report.paused is True
        assert report.ran == 0


class TestDegradation:
    def test_missing_config_disables_automation_without_bricking_the_core(
        self, tmp_path
    ):
        """Fail closed, not fail dead (07 F8's shape). A missing kang.toml
        means no scheduled work — never an invented schedule — but Kang's
        manual use of the system must survive it."""
        config = tmp_path / "config"
        config.mkdir(parents=True, exist_ok=True)
        (config / "permissions.toml").write_text(
            (DEFAULTS / "permissions.toml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        built = build_core(tmp_path)  # no kang.toml
        try:
            assert built.scheduler is None  # automation off
            # ...but the Core still serves
            result = _call(built, "task.create", {"title": "still works"}, "t1")
            assert result["task_id"]
        finally:
            built.close()
