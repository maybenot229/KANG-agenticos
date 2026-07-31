"""RELEASE-BLOCKING: the deterministic Planner (05 §16, 13 §2.6, 18 §3 M5).

FR-001 has no model-availability clause — the plan exists every morning with
zero models, zero network, zero budget. This suite proves the floor:

  same inputs ⇒ byte-identical plan, byte-identical ordering

`build_plan` is pure, so "byte-identical" is asserted against a canonical
JSON serialisation of the plan, not just field equality — a reordering that
compared equal as a set would still be a determinism failure.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from kang.domain.planner import MAX_QUESTS, PlanInputs, build_plan
from kang.domain.ports.calendar_store import CalendarEvent
from kang.domain.ports.deadline_store import Deadline
from kang.domain.ports.task_store import Task

DAY = "2026-03-02"
MOMENT = datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc)


def _task(index: int, priority: int = 3, due: str | None = None, **overrides) -> Task:
    fields = dict(
        id=f"task-{index:04d}",
        title=f"task {index}",
        status="open",
        priority=priority,
        due=due,
        created_at=MOMENT,
        updated_at=MOMENT,
        device_id="device-test",
        revision=1,
    )
    fields.update(overrides)
    return Task(**fields)


def _deadline(index: int, at: str) -> Deadline:
    return Deadline(
        id=f"dl-{index:04d}",
        kind="custom",
        title=f"deadline {index}",
        at=at,
        status="tracked",
        created_at=MOMENT,
        updated_at=MOMENT,
        device_id="device-test",
        revision=1,
    )


def _event(index: int, starts: str) -> CalendarEvent:
    return CalendarEvent(
        provider_event_id=f"ev-{index:04d}",
        calendar_id="primary",
        title=f"event {index}",
        starts=starts,
        fetched_at=MOMENT.isoformat(),
    )


def _inputs(**overrides) -> PlanInputs:
    fields = dict(
        plan_date=DAY,
        tasks=(_task(1, priority=2), _task(2, priority=1), _task(3, priority=3)),
        deadlines=(_deadline(1, "2026-03-05T09:00:00+00:00"),),
        calendar=(_event(1, f"{DAY}T08:00:00+00:00"),),
    )
    fields.update(overrides)
    return PlanInputs(**fields)


def _canonical(plan) -> str:
    """A byte-stable rendering of the plan — order-sensitive by construction."""
    return json.dumps(
        {
            "plan_date": plan.plan_date,
            "quests": [t.id for t in plan.quests],
            "deadlines": [d.id for d in plan.deadlines],
            "calendar": [e.provider_event_id for e in plan.calendar],
            "estimated_minutes": plan.estimated_minutes,
            "deferred_count": plan.deferred_count,
        },
        sort_keys=True,
    )


class TestDeterminism:
    def test_same_inputs_produce_a_byte_identical_plan(self):
        assert _canonical(build_plan(_inputs())) == _canonical(build_plan(_inputs()))

    def test_input_order_does_not_change_the_plan(self):
        """The plan must depend on the DATA, not on how it was fetched."""
        forward = _inputs()
        reversed_inputs = PlanInputs(
            plan_date=forward.plan_date,
            tasks=tuple(reversed(forward.tasks)),
            deadlines=tuple(reversed(forward.deadlines)),
            calendar=tuple(reversed(forward.calendar)),
        )
        assert _canonical(build_plan(forward)) == _canonical(
            build_plan(reversed_inputs)
        )

    def test_equal_priority_and_due_still_orders_totally(self):
        """The id tiebreak is what makes the order total rather than merely
        sorted — without it, two equal tasks could swap between runs."""
        tasks = (_task(9, priority=2), _task(4, priority=2), _task(7, priority=2))
        plan = build_plan(_inputs(tasks=tasks))
        assert [t.id for t in plan.quests] == ["task-0004", "task-0007", "task-0009"]

    def test_no_model_or_clock_is_reachable_from_the_planner(self):
        """05 §16 / 18 §7.6: the deterministic path must have no model in it.
        Structural, so it stays true as the module grows."""
        from pathlib import Path

        import kang.domain.planner.plan_service as plan_service

        source = Path(plan_service.__file__).read_text(encoding="utf-8")
        for forbidden in ("import requests", "anthropic", "openai", "datetime.now"):
            assert forbidden not in source, f"planner reached for {forbidden}"


class TestOrdering:
    def test_priority_one_comes_first(self):
        plan = build_plan(_inputs())
        assert plan.quests[0].id == "task-0002"  # priority 1

    def test_sooner_due_wins_within_a_priority(self):
        tasks = (
            _task(1, priority=2, due="2026-04-01"),
            _task(2, priority=2, due="2026-03-03"),
        )
        plan = build_plan(_inputs(tasks=tasks))
        assert [t.id for t in plan.quests] == ["task-0002", "task-0001"]

    def test_undated_tasks_sort_after_dated_ones(self):
        tasks = (_task(1, priority=2), _task(2, priority=2, due="2026-12-31"))
        plan = build_plan(_inputs(tasks=tasks))
        assert [t.id for t in plan.quests] == ["task-0002", "task-0001"]


class TestSelection:
    def test_quests_are_capped(self):
        tasks = tuple(_task(i) for i in range(MAX_QUESTS + 3))
        plan = build_plan(_inputs(tasks=tasks))
        assert len(plan.quests) == MAX_QUESTS
        assert plan.deferred_count == 3

    def test_finished_and_deferred_tasks_are_excluded(self):
        tasks = (
            _task(1, status="done"),
            _task(2, status="dropped"),
            _task(3, status="deferred"),  # Kang's explicit "not now" (P6)
            _task(4, status="open"),
        )
        plan = build_plan(_inputs(tasks=tasks))
        assert [t.id for t in plan.quests] == ["task-0004"]

    def test_workload_sums_only_the_chosen_quests(self):
        tasks = tuple(_task(i, estimate_min=10) for i in range(MAX_QUESTS + 2))
        plan = build_plan(_inputs(tasks=tasks))
        assert plan.estimated_minutes == MAX_QUESTS * 10

    def test_missing_estimates_do_not_break_the_workload(self):
        tasks = (_task(1, estimate_min=30), _task(2))
        assert build_plan(_inputs(tasks=tasks)).estimated_minutes == 30


class TestOfflineFloor:
    def test_a_plan_exists_with_no_tasks_deadlines_or_calendar(self):
        """NFR-002 / FR-001: the plan exists every morning, even empty —
        an empty plan is honest; no plan is a broken promise."""
        plan = build_plan(
            PlanInputs(plan_date=DAY, tasks=(), deadlines=(), calendar=())
        )
        assert plan.plan_date == DAY
        assert plan.quests == ()
        assert plan.estimated_minutes == 0

    def test_a_plan_exists_with_no_calendar_provider(self):
        """The calendar stub returns nothing until a provider is configured;
        that must degrade to a plan, not an error."""
        plan = build_plan(_inputs(calendar=()))
        assert plan.quests  # tasks still planned
        assert plan.calendar == ()
