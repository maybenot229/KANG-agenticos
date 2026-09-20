"""The structured store, conversations, and tombstones (ADR-049 D2).

Goals, projects, competitions, milestones, tasks, deadlines give the `about_*`
links real ids and the P0 read shapes (`TaskStore.plannable`,
`DeadlineStore.active`) real rows. Conversations/messages give `fts_message`
content and `from_conversation` links real ids.
"""

from __future__ import annotations

from datetime import timedelta

from ._ctx import Ctx, Weighted, iso, later
from .profiles import (
    DEADLINE_STATUSES,
    PROJECT_STATUSES,
    TASK_STATUSES,
)

_QUARTER_YEAR_LIFE = Weighted((("quarter", 40), ("year", 45), ("life", 15)))
_GOAL_STATUS = Weighted(
    (("active", 60), ("achieved", 20), ("revised", 10), ("retired", 10))
)
_PROJECT_STATUS = Weighted(PROJECT_STATUSES)
_COMP_STATUS = Weighted(
    (
        ("discovered", 10),
        ("evaluating", 10),
        ("entered", 20),
        ("skipped", 20),
        ("submitted", 10),
        ("judged", 20),
        ("archived", 10),
    )
)
_MILESTONE_STATUS = Weighted(
    (("pending", 25), ("reached", 55), ("missed", 10), ("dropped", 10))
)
_TASK_STATUS = Weighted(TASK_STATUSES)
_DEADLINE_STATUS = Weighted(DEADLINE_STATUSES)
_DEADLINE_KIND = Weighted(
    (
        ("registration", 20),
        ("submission", 30),
        ("event", 15),
        ("school", 25),
        ("custom", 10),
    )
)


def _sync_tail(ctx: Ctx, at: str) -> tuple:
    return (at, at, ctx.device(), 1)


def generate_structured(ctx: Ctx) -> None:
    p = ctx.profile
    _goals(ctx, p.goals)
    _projects(ctx, p.projects)
    _competitions(ctx, p.competitions)
    _milestones(ctx, p.milestones)
    _tasks(ctx, p.tasks)
    _deadlines(ctx, p.deadlines)


def _goals(ctx: Ctx, count: int) -> None:
    rows = []
    for moment in ctx.timeline(count):
        at = iso(moment)
        gid = ctx.new_id(moment)
        ctx.goal_ids.append(gid)
        rows.append(
            (
                gid,
                ctx.vocab.title(ctx.rng),
                ctx.vocab.sentence(ctx.rng),
                _QUARTER_YEAR_LIFE.pick(ctx.rng),
                _GOAL_STATUS.pick(ctx.rng),
                *_sync_tail(ctx, at),
            )
        )
    ctx.write(
        "INSERT INTO goal (id, title, description, horizon, status, created_at, "
        "updated_at, device_id, revision) VALUES (?,?,?,?,?,?,?,?,?)",
        rows,
    )


def _projects(ctx: Ctx, count: int) -> None:
    rows = []
    for moment in ctx.timeline(count):
        at = iso(moment)
        pid = ctx.new_id(moment)
        ctx.project_ids.append(pid)
        goal_id = ctx.rng.choice(ctx.goal_ids) if ctx.rng.random() < 0.7 else None
        if goal_id:
            ctx.fk_edges.append((f"project:{pid}", f"goal:{goal_id}", "about_goal"))
        repo = f"example-org/{ctx.rng.choice(ctx.vocab.domain_words)}-{len(rows)}"
        rows.append(
            (
                pid,
                ctx.vocab.title(ctx.rng),
                ctx.vocab.sentence(ctx.rng),
                _PROJECT_STATUS.pick(ctx.rng),
                None,
                repo if ctx.rng.random() < 0.4 else None,
                goal_id,
                *_sync_tail(ctx, at),
            )
        )
    ctx.write(
        "INSERT INTO project (id, name, description, status, vault_folder, "
        "github_repo, goal_id, created_at, updated_at, device_id, revision) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )


def _competitions(ctx: Ctx, count: int) -> None:
    rows = []
    for moment in ctx.timeline(count):
        at = iso(moment)
        cid = ctx.new_id(moment)
        ctx.competition_ids.append(cid)
        project_id = ctx.rng.choice(ctx.project_ids) if ctx.rng.random() < 0.4 else None
        if project_id:
            ctx.fk_edges.append(
                (f"competition:{cid}", f"project:{project_id}", "about_project")
            )
        rows.append(
            (
                cid,
                ctx.vocab.title(ctx.rng),
                f"https://example.org/c/{len(rows)}",
                _COMP_STATUS.pick(ctx.rng),
                None,
                None,
                project_id,
                *_sync_tail(ctx, at),
            )
        )
    ctx.write(
        "INSERT INTO competition (id, name, url, status, evaluation, result, "
        "project_id, created_at, updated_at, device_id, revision) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )


def _milestones(ctx: Ctx, count: int) -> None:
    rows = []
    for moment in ctx.timeline(count):
        at = iso(moment)
        mid = ctx.new_id(moment)
        project_id = ctx.rng.choice(ctx.project_ids)
        ctx.fk_edges.append(
            (f"milestone:{mid}", f"project:{project_id}", "about_project")
        )
        rows.append(
            (
                mid,
                project_id,
                ctx.vocab.title(ctx.rng),
                iso(later(moment, 14 * 86400)),
                _MILESTONE_STATUS.pick(ctx.rng),
                *_sync_tail(ctx, at),
            )
        )
    ctx.write(
        "INSERT INTO milestone (id, project_id, title, due, status, created_at, "
        "updated_at, device_id, revision) VALUES (?,?,?,?,?,?,?,?,?)",
        rows,
    )


def _tasks(ctx: Ctx, count: int) -> None:
    rows = []
    for moment in ctx.timeline(count):
        at = iso(moment)
        tid = ctx.new_id(moment)
        project_id = ctx.rng.choice(ctx.project_ids) if ctx.rng.random() < 0.6 else None
        if project_id:
            ctx.fk_edges.append(
                (f"task:{tid}", f"project:{project_id}", "about_project")
            )
        status = _TASK_STATUS.pick(ctx.rng)
        due = iso(later(moment, ctx.rng.randint(1, 30) * 86400))
        plan = iso(moment)[:10] if status in ("open", "scheduled") else None
        estimate = ctx.rng.choice((15, 30, 45, 60, 90, 120))
        done = status == "done"
        rows.append(
            (
                tid,
                project_id,
                ctx.vocab.title(ctx.rng),
                None,
                status,
                ctx.rng.randint(1, 5),
                due,
                plan,
                estimate,
                estimate + ctx.rng.randint(-10, 30) if done else None,
                iso(later(moment, 86400)) if done else None,
                *_sync_tail(ctx, at),
            )
        )
    ctx.write(
        "INSERT INTO task (id, project_id, title, notes, status, priority, due, "
        "plan_date, estimate_min, actual_min, completed_at, created_at, "
        "updated_at, device_id, revision) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )


def _deadlines(ctx: Ctx, count: int) -> None:
    rows = []
    for moment in ctx.timeline(count):
        at = iso(moment)
        did = ctx.new_id(moment)
        kind = _DEADLINE_KIND.pick(ctx.rng)
        competition_id = project_id = None
        if kind in ("registration", "submission", "event"):
            if ctx.rng.random() < 0.6:
                competition_id = ctx.rng.choice(ctx.competition_ids)
                ctx.fk_edges.append(
                    (
                        f"deadline:{did}",
                        f"competition:{competition_id}",
                        "about_competition",
                    )
                )
            else:
                project_id = ctx.rng.choice(ctx.project_ids)
                ctx.fk_edges.append(
                    (f"deadline:{did}", f"project:{project_id}", "about_project")
                )
        rows.append(
            (
                did,
                competition_id,
                project_id,
                kind,
                ctx.vocab.title(ctx.rng),
                iso(later(moment, ctx.rng.randint(1, 60) * 86400)),
                "[14,7,3,1]",
                _DEADLINE_STATUS.pick(ctx.rng),
                *_sync_tail(ctx, at),
            )
        )
    ctx.write(
        "INSERT INTO deadline (id, competition_id, project_id, kind, title, at, "
        "lead_days, status, created_at, updated_at, device_id, revision) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )


_ROLE_CYCLE = ("kang", "agent")


def generate_conversations(ctx: Ctx) -> None:
    p = ctx.profile
    convo_rows, message_rows = [], []
    starts = list(ctx.timeline(p.conversations))
    per = p.messages // p.conversations
    for start in starts:
        cid = ctx.new_id(start)
        ctx.conversation_ids.append(cid)
        moment = start
        for turn in range(per):
            moment = moment + timedelta(seconds=ctx.rng.randint(5, 240))
            role = (
                "kang_system"
                if turn == per - 1 and ctx.rng.random() < 0.1
                else _ROLE_CYCLE[turn % 2]
            )
            message_rows.append(
                (
                    ctx.new_id(moment),
                    cid,
                    role,
                    ctx.vocab.sentences(ctx.rng, ctx.rng.randint(1, 3)),
                    iso(moment),
                )
            )
        convo_rows.append(
            (cid, iso(start), iso(moment), ctx.vocab.title(ctx.rng), per, 0)
        )
    ctx.write(
        "INSERT INTO conversation (id, started, last_message, title, message_count, "
        "purged) VALUES (?,?,?,?,?,?)",
        convo_rows,
    )
    ctx.write(
        "INSERT INTO message (id, conversation_id, role, content, at) "
        "VALUES (?,?,?,?,?)",
        message_rows,
    )


_TOMB_ENTITY = Weighted((("memory_record", 50), ("task", 30), ("episode", 20)))
_TOMB_POLICY = Weighted((("kang:explicit", 60), ("memory.toml:retention", 40)))


def generate_tombstones(ctx: Ctx) -> None:
    rows = []
    for moment in ctx.timeline(ctx.profile.tombstones):
        rows.append(
            (
                ctx.new_id(moment),
                _TOMB_ENTITY.pick(ctx.rng),
                iso(moment),
                "kang" if ctx.rng.random() < 0.6 else "rule:janitor",
                _TOMB_POLICY.pick(ctx.rng),
            )
        )
    ctx.write(
        "INSERT INTO tombstone (id, entity, deleted_at, deleted_by, policy_ref) "
        "VALUES (?,?,?,?,?)",
        rows,
    )
