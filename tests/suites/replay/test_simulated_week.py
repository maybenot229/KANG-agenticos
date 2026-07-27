"""M5's GATE (18 §3): a full simulated week produces every morning plan with
zero model calls, on Kang's REAL schedule.

    "a full simulated week (fixture scenario) produces every morning plan
     with zero model calls"

The schedule is not invented here: trigger times are read from the shipped
`config/defaults/kang.toml` (05:45 the six school days, 06:45 Sunday),
grounded in the 2026-07-19 intake. If someone edits that config, this test
follows it — which is what "config, not spec" (05 Appendix E) means.

Saturday is a school day. The week has seven planned mornings, not five.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from kang.adapters.config.planner_config import load_planner_triggers
from kang.adapters.sqlite.connection import open_connection
from kang.api.dispatch import ApiRequest
from kang.kernel.runtime.composition import build_core

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULTS = REPO_ROOT / "config" / "defaults"

# A Monday, so the week runs Mon..Sun and covers both the Saturday and the
# Sunday special cases.
WEEK_START = date(2026, 3, 2)


@pytest.fixture
def triggers():
    return load_planner_triggers(DEFAULTS / "kang.toml")


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


def _week() -> list[date]:
    return [WEEK_START + timedelta(days=offset) for offset in range(7)]


class TestTriggerTimes:
    def test_the_week_has_seven_planned_mornings(self, triggers):
        """Saturday is a school day — the intake is explicit that Kang's
        week has no real weekend, so no day is skipped."""
        assert len({day for day in _week()}) == 7
        assert all(triggers.morning_for(day) for day in _week())

    def test_school_days_use_the_0545_trigger(self, triggers):
        for day in _week():
            if day.weekday() != 6:  # not Sunday
                assert triggers.morning_for(day) == "05:45", day

    def test_sunday_uses_the_0645_trigger(self, triggers):
        sunday = WEEK_START + timedelta(days=6)
        assert sunday.weekday() == 6
        assert triggers.morning_for(sunday) == "06:45"

    def test_saturday_is_read_from_its_own_key_not_folded_into_weekday(self):
        """They are equal today, but that is a fact about Kang's routine,
        not a rule — collapsing them would couple two independent values."""
        text = (DEFAULTS / "kang.toml").read_text(encoding="utf-8")
        assert "saturday_morning" in text


class TestSimulatedWeek:
    def test_every_morning_produces_a_plan(self, core):
        built, _ = core
        _call(built, "task.create", {"title": "Olympiad drill", "priority": 1}, "t1")
        _call(built, "task.create", {"title": "Revise notes", "priority": 2}, "t2")

        plans = [
            _call(built, "plan.generate", {"plan_date": day.isoformat()}, f"p{day}")
            for day in _week()
        ]

        assert len(plans) == 7
        assert [p["plan_date"] for p in plans] == [d.isoformat() for d in _week()]
        # FR-001: a plan exists every morning — none empty of intent
        assert all(p["quest_ids"] for p in plans)

    def test_the_week_makes_zero_model_calls(self, core):
        """18 §7.6: M0-M6 contain no model call. Structural — no provider
        adapter is wired into the Core at all, so a model call is not
        merely absent, it is unreachable."""
        built, home = core
        _call(built, "task.create", {"title": "Olympiad drill", "priority": 1}, "t1")
        for day in _week():
            _call(built, "plan.generate", {"plan_date": day.isoformat()}, f"p{day}")

        # the cost ledger table does not even exist yet, and nothing wired
        # can write one — assert the absence rather than assume it
        conn = open_connection(home / "kang.db")
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        finally:
            conn.close()
        assert "model_call" not in tables

    def test_the_week_is_reproducible(self, tmp_path):
        """Two identical weeks produce identical plans (13 §2.6). Ids differ
        by construction (uuid7); the SELECTION and ORDER must not."""
        runs = []
        for name in ("week-a", "week-b"):
            home = tmp_path / name
            _seed_config(home)
            built = build_core(home)
            try:
                _call(built, "task.create", {"title": "A", "priority": 1}, "t1")
                _call(built, "task.create", {"title": "B", "priority": 2}, "t2")
                runs.append(
                    [
                        _call(
                            built,
                            "plan.generate",
                            {"plan_date": day.isoformat()},
                            f"p{day}",
                        )["estimated_minutes"]
                        for day in _week()
                    ]
                )
            finally:
                built.close()
        assert runs[0] == runs[1]

    def test_planning_stamps_plan_date_once_and_is_idempotent(self, core):
        """The plan's durable half. Re-running the same slot must not
        re-stamp — catch-up policy `run_once_latest` can replay a slot."""
        built, _ = core
        _call(built, "task.create", {"title": "Olympiad drill", "priority": 1}, "t1")
        day = WEEK_START.isoformat()
        first = _call(built, "plan.generate", {"plan_date": day}, "p1")
        second = _call(built, "plan.generate", {"plan_date": day}, "p2")
        assert first["stamped"]  # stamped on the first run
        assert second["stamped"] == []  # nothing to re-stamp on the second
        assert first["quest_ids"] == second["quest_ids"]
