"""Planner domain service — the deterministic morning plan.

Layer: domain/planner (17 §2: "plans, capacity, the deterministic path").
Pure and total: no I/O, no clock read, no randomness. Every input arrives as
an argument, so the same inputs produce a byte-identical plan — which is the
release-blocking claim (05 §16, 13 §2.6, 18 §3 M5's gate).

Constitutional home: 02_PRD FR-001 ("KANG shall generate a daily plan
(quests, schedule, deadlines, priorities) every morning without prompting"),
02_PRD §10.4 (the plan's contents), 09_UI §4 (Today's Quests, 3–5),
05_AGENTS Appendix A (the planner's degradation ladder bottoms out at
"**deterministic plan** from P0 data" — this module IS that floor, built
before any model exists to fall back from, per 18 §7.6).

THIS IS THE ZERO-MODEL PATH. Nothing here may ever call a model, consult a
provider, or read a clock. FR-001 has no model-availability clause: the plan
exists every morning even with zero network, zero providers, and zero
budget. If a future contributor needs "smarter" ordering, that belongs in a
cognitive layer ABOVE this one that may degrade back to exactly this.
"""

from __future__ import annotations

from dataclasses import dataclass

from kang.domain.ports.calendar_store import CalendarEvent
from kang.domain.ports.deadline_store import Deadline
from kang.domain.ports.task_store import Task

__all__ = [
    "MAX_QUESTS",
    "Plan",
    "PlanInputs",
    "build_plan",
    "plan_generated_payload",
]

# 09_UI §4: "Today's Quests (3–5, from the Planner)". The upper bound is the
# constraint that matters — a plan that lists everything is not a plan.
MAX_QUESTS = 5

# Tasks eligible to be planned. `done`/`dropped` are finished; `deferred` is
# Kang's explicit "not now" and the Planner does not overrule him (P6).
_PLANNABLE_STATUSES = ("open", "scheduled")


@dataclass(frozen=True)
class PlanInputs:
    """Everything the plan is derived from (11 §4: beyond a few parameters,
    a dataclass). Passing inputs rather than stores is what keeps this
    module pure and the determinism suite honest."""

    plan_date: str  # ISO date, YYYY-MM-DD
    tasks: tuple[Task, ...]
    deadlines: tuple[Deadline, ...]
    calendar: tuple[CalendarEvent, ...]


@dataclass(frozen=True)
class Plan:
    """One day's plan. Derived state (02_PRD's dependency map) — rebuildable
    from its inputs, never authoritative, which is why no `plan` table
    exists and why `plan.generated` is not recovery-grade (ADR-004)."""

    plan_date: str
    quests: tuple[Task, ...]
    deadlines: tuple[Deadline, ...]
    calendar: tuple[CalendarEvent, ...]
    estimated_minutes: int
    deferred_count: int


def _quest_rank(task: Task) -> tuple:
    """The total order over candidate tasks.

    Deterministic and total: priority first (1 is highest, 07 §5.2's CHECK),
    then the nearest due date, then id. The id tiebreak is what makes the
    order *total* rather than merely sorted — two tasks with equal priority
    and due date must still order identically on every run (13 §2.6).

    `due` is None for undated tasks, which must sort AFTER dated ones; the
    leading boolean does that without inventing a sentinel date.

    NOT considered here: deadline urgency. Deadlines are surfaced in the
    plan but do not reorder tasks — see `build_plan`'s note.
    """
    return (task.priority, task.due is None, task.due or "", task.id)


def build_plan(inputs: PlanInputs) -> Plan:
    """Build the day's plan. Pure: same inputs ⇒ identical Plan.

    Deadlines are *surfaced*, not scored into the task order. That is a
    deliberate limit, not an oversight: ordering tasks by deadline urgency
    would require deciding when a deadline becomes "in danger today"
    (05 §13's `critical` row names the concept but never defines the
    threshold), and inventing a number here would bake a product decision
    into sort logic where nobody would ever find it again. Kang's call —
    flagged, not guessed. Until then the plan shows the deadlines plainly
    and lets priority drive the order.
    """
    candidates = tuple(t for t in inputs.tasks if t.status in _PLANNABLE_STATUSES)
    ranked = tuple(sorted(candidates, key=_quest_rank))
    quests = ranked[:MAX_QUESTS]
    return Plan(
        plan_date=inputs.plan_date,
        quests=quests,
        # Active deadlines, soonest first — the store already returns them in
        # (at, id) order; re-sorting here keeps the plan's order independent
        # of how it was fetched.
        deadlines=tuple(sorted(inputs.deadlines, key=lambda d: (d.at, d.id))),
        calendar=tuple(
            sorted(inputs.calendar, key=lambda e: (e.starts, e.provider_event_id))
        ),
        estimated_minutes=sum(t.estimate_min or 0 for t in quests),
        # What did not fit today. Surfaced as a count so the plan is honest
        # about being a selection rather than the whole list (P3).
        deferred_count=len(ranked) - len(quests),
    )


def plan_generated_payload(plan: Plan) -> dict:
    """The `plan.generated` payload. Non-recovery-grade (ADR-004), so this
    carries ids and counts rather than whole rows: the plan is derived, and
    its durable half is the `plan_date` stamped on each quest, which rides
    the recovery-grade `task.updated` events instead."""
    return {
        "plan_date": plan.plan_date,
        "quest_ids": [t.id for t in plan.quests],
        "deadline_ids": [d.id for d in plan.deadlines],
        "estimated_minutes": plan.estimated_minutes,
        "deferred_count": plan.deferred_count,
    }
