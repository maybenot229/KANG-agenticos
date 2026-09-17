"""The operation registry literal, part 2 of 2 — every `_op(...)` entry
from `held_action.*` through `chat.send` (12_API §16).

Layer: api.
Constitutional home: same as `operations.py`'s own module docstring —
this file exists purely because that one crossed the size lint's line
limit (2026-09-17, ADR-047), not because this half means anything
different from the first. `OperationChannel`/`OperationSchemas`/`_op`
live in `operations.py`; this file only adds more entries built with
them. `kang.api.registry`'s own `__init__.py` concatenates
`operations.OPERATIONS + operations_ext.EXTRA_OPERATIONS` into the one
`OPERATIONS` every external caller imports.
"""

from __future__ import annotations

from typing import Any

from kang.api.registry.operations import OperationChannel, OperationSchemas, _op
from kang.api.schemas.audit import AuditListRequest, AuditListResponse
from kang.api.schemas.backup import (
    BackupOffsiteCheckRequest,
    BackupOffsiteCheckResponse,
    BackupSnapshotRequest,
    BackupSnapshotResponse,
    BackupVerifyRequest,
    BackupVerifyResponse,
)
from kang.api.schemas.chat import ChatSendRequest, ChatSendResponse
from kang.api.schemas.competition import (
    CompetitionCreateRequest,
    CompetitionCreateResponse,
    CompetitionListRequest,
    CompetitionListResponse,
)
from kang.api.schemas.goal import (
    GoalCreateRequest,
    GoalCreateResponse,
    GoalListRequest,
    GoalListResponse,
    GoalTransitionRequest,
    GoalTransitionResponse,
)
from kang.api.schemas.held_action import (
    HeldActionApproveRequest,
    HeldActionApproveResponse,
    HeldActionCancelRequest,
    HeldActionCancelResponse,
    HeldActionExpireRequest,
    HeldActionExpireResponse,
    HeldActionListRequest,
    HeldActionListResponse,
)
from kang.api.schemas.invocation import (
    InvocationListRequest,
    InvocationListResponse,
)
from kang.api.schemas.job import JobDisableRequest, JobEnableRequest
from kang.api.schemas.milestone import (
    MilestoneCreateRequest,
    MilestoneCreateResponse,
    MilestoneListRequest,
    MilestoneListResponse,
    MilestoneTransitionRequest,
    MilestoneTransitionResponse,
)
from kang.api.schemas.project import (
    ProjectCompleteRequest,
    ProjectCompleteResponse,
    ProjectCreateRequest,
    ProjectCreateResponse,
    ProjectListRequest,
    ProjectListResponse,
)
from kang.api.schemas.system import SystemHealthRequest, SystemHealthResponse

__all__ = ["EXTRA_OPERATIONS"]

EXTRA_OPERATIONS: tuple[dict[str, Any], ...] = (
    # held_action.* (ADR 001, ADR 002): channel-gated, not scope-gated — no
    # `kang`-only scope exists for these (API-003/SEC-004: first-party-only
    # is a channel, never a grant). ADR-027 D2 re-confirmed this rather than
    # scoping them for uniformity: 05_AGENTS §D is normative that "the
    # first-party channel check (not a permission scope — §8) is what stands
    # in for that second layer", so adding a scope would imply a grant could
    # substitute for the channel. It cannot; no grant satisfies first_party.
    # Handlers wired 2026-08-05
    # (operations.py::make_held_action_approve_handler/
    # make_held_action_cancel_handler) — transition-only (pending ->
    # approved | cancelled); driving an approved action's effect to
    # `executed` is a separate, still-open gap (see that handler's own
    # docstring for why: the row has no stored params to replay against).
    #
    # commit_mode="transactional" here describes THESE operations' own
    # direct effect — a `held_action.status` flip, always representable as
    # one `kang.db` write (ADR-001 Amendment's default case) — not the
    # commit_mode of whatever operation the held action names, which is
    # separate registry metadata on that operation's own entry and only
    # matters once effect-driving is built.
    _op(
        "held_action.approve",
        "command",
        None,
        True,
        "Approve a pending held action; drives its effect per commit_mode.",
        channel=OperationChannel(first_party_only=True, commit_mode="transactional"),
        schemas=OperationSchemas(
            request=HeldActionApproveRequest, response=HeldActionApproveResponse
        ),
    ),
    _op(
        "held_action.cancel",
        "command",
        None,
        True,
        "Decline a pending held action.",
        channel=OperationChannel(first_party_only=True, commit_mode="transactional"),
        schemas=OperationSchemas(
            request=HeldActionCancelRequest, response=HeldActionCancelResponse
        ),
    ),
    # held_action.list: added 2026-08-05 for the dashboard's Zone 2
    # approval queue and the confirm dialog (09_UI §4/§7). Scope-gated
    # (`held_actions.read`, following `deadlines.read`'s naming pattern),
    # not channel-gated: unlike approve/cancel, listing pending held
    # actions isn't on 05_AGENTS Appendix D's closed list — it's a read,
    # not the consequential step itself. No commit_mode: not consequential.
    _op(
        "held_action.list",
        "query",
        "held_actions.read",
        False,
        "List every pending held action, oldest first.",
        schemas=OperationSchemas(
            request=HeldActionListRequest, response=HeldActionListResponse
        ),
    ),
    # held_action.expire (ADR-022): the missing operation wrapping
    # HeldActionStore.expire_due(), which had no caller anywhere before
    # this. Same shape as deadline.sweep (command, no request fields,
    # idempotent — expiring a slot twice degrades to zero further work).
    # No commit_mode: not consequential, same reasoning deadline.sweep's
    # own entry already gives.
    _op(
        "held_action.expire",
        "command",
        "held_actions.expire",
        True,
        "Cancel every pending held action past its 24h expiry window.",
        schemas=OperationSchemas(
            request=HeldActionExpireRequest, response=HeldActionExpireResponse
        ),
    ),
    # backup.snapshot (ADR-031): the daily snapshot job's operation. The
    # mechanisms (backup.py's integrity_check/vacuum_into) shipped at M1
    # and had ZERO callers until this — the module header's own promise
    # that "the scheduled daily job (02:30) arrives with the scheduler at
    # M3" expired unnoticed. Named by 05_AGENTS Appendix E, not invented
    # here. No commit_mode: it writes no kang.db state, so it is not
    # consequential in ADR-001's sense; not first_party_only, matching
    # deadline.sweep — routine automated maintenance.
    _op(
        "backup.snapshot",
        "command",
        "backups.write",
        True,
        "Snapshot the database and event log, record the manifest, prune.",
        schemas=OperationSchemas(
            request=BackupSnapshotRequest, response=BackupSnapshotResponse
        ),
    ),
    # backup.verify (ADR-032): the monthly restore test 07 Part XII.3
    # requires — "a backup that hasn't been restore-tested is treated as
    # nonexistent." Same scope as backup.snapshot: both act on the
    # backups/ directory, and this one also appends to the same manifest.
    _op(
        "backup.verify",
        "command",
        "backups.write",
        True,
        "Restore-test the latest daily snapshot; report, never gate.",
        schemas=OperationSchemas(
            request=BackupVerifyRequest, response=BackupVerifyResponse
        ),
    ),
    # backup.offsite_check (ADR-034): 07 Part XII.5's off-machine warning
    # — reads the Kang-configured marker's mtime and, when stale,
    # announces `backup.offsite_stale`. New scope, `backups.read`, rather
    # than reusing `backups.write`: unlike its two siblings above, this
    # operation writes no file and appends no manifest line — reusing
    # the write scope would overstate what it does.
    _op(
        "backup.offsite_check",
        "command",
        "backups.read",
        True,
        "Check for evidence of an off-machine backup; warn if stale.",
        schemas=OperationSchemas(
            request=BackupOffsiteCheckRequest, response=BackupOffsiteCheckResponse
        ),
    ),
    # audit.list / system.health: added 2026-08-05 for the System domain's
    # Activity and Health views (09_UI §12). Both were scope=None on the
    # reasoning that system metadata is not a domain resource; ADR-027
    # scoped them (`audit.read`/`system.read`) because that reasoning held
    # only while every session principal was fully trusted (`kang`,
    # `kernel:scheduler`). 05_AGENTS §8 adds `agent:{id}`, and SEC-004
    # allows no code path exempt from scopes but `kang`.
    _op(
        "audit.list",
        "query",
        "audit.read",
        False,
        "List every audit record of one month, oldest first.",
        schemas=OperationSchemas(request=AuditListRequest, response=AuditListResponse),
    ),
    _op(
        "system.health",
        "query",
        "system.read",
        False,
        "List every scheduled job's status and whether automation is paused.",
        schemas=OperationSchemas(
            request=SystemHealthRequest, response=SystemHealthResponse
        ),
    ),
    # job.disable / job.enable (ADR-021): the first real consequential
    # operation — 12_API.md §11 already named "job.enable/disable
    # (consequential for core jobs)" before any code existed. Neither
    # handler ever performs the effect itself (see
    # `operations/job_ops.py`'s own module docstring) — commit_mode here
    # describes what `held_action.approve` must do once approved, not
    # anything this operation's own handler does directly (same
    # distinction `held_action.approve`'s own entry's comment already
    # draws for its own effect). No response_schema: the handler's only
    # real return is the `confirmation_required` error envelope, never a
    # success shape (see `schemas/job.py`'s own docstring).
    _op(
        "job.disable",
        "command",
        "jobs.write",
        True,
        "Disable a scheduled job (requires confirmation).",
        channel=OperationChannel(commit_mode="transactional"),
        schemas=OperationSchemas(request=JobDisableRequest),
    ),
    _op(
        "job.enable",
        "command",
        "jobs.write",
        True,
        "Enable a scheduled job (requires confirmation).",
        channel=OperationChannel(commit_mode="transactional"),
        schemas=OperationSchemas(request=JobEnableRequest),
    ),
    # invocation.list: added 2026-08-05 for the System-domain Invocations
    # view (09_UI §12). scope=None, matching audit.list/system.health's own
    # precedent just above — the execution ledger is system metadata about
    # the Core itself, not a domain resource a domain-verb scope would fit.
    # Unlike those two, this is genuinely new port surface
    # (`InvocationStore.recent()`), not pure exposure of something that
    # already existed — `InvocationStore` had no list method at all before
    # this (only `by_correlation`, a point lookup).
    _op(
        "invocation.list",
        "query",
        "invocations.read",
        False,
        "List the most recent invocations, newest first.",
        schemas=OperationSchemas(
            request=InvocationListRequest, response=InvocationListResponse
        ),
    ),
    # project.create / project.list (ADR-013): the Projects domain's first
    # real operations, tracking only. Scope follows deadline.*'s exact
    # naming convention (05 §9 domain-verb vocabulary) — `projects.write`
    # already named in 05_AGENTS §9's tool-access table (competition_scout/
    # _strategist/researcher all hold it); `projects.read` is new, mirroring
    # `deadlines.read`/`held_actions.read`'s own precedent of a read-only
    # sibling scope. Not consequential (05 Appendix D's closed list names
    # `projects.delete`, not create), so no commit_mode.
    _op(
        "project.create",
        "command",
        "projects.write",
        True,
        "Track a new project.",
        schemas=OperationSchemas(
            request=ProjectCreateRequest, response=ProjectCreateResponse
        ),
    ),
    _op(
        "project.list",
        "query",
        "projects.read",
        False,
        "List every tracked project, name then id.",
        schemas=OperationSchemas(
            request=ProjectListRequest, response=ProjectListResponse
        ),
    ),
    # project.complete (ADR-018): the entity's first status transition,
    # active -> completed. Same scope as project.create (no new
    # authority). pause/resume/archive/abandon stay unbuilt (ADR-018's
    # own scope ruling).
    _op(
        "project.complete",
        "command",
        "projects.write",
        True,
        "Mark a project completed.",
        schemas=OperationSchemas(
            request=ProjectCompleteRequest, response=ProjectCompleteResponse
        ),
    ),
    # competition.create / competition.list (ADR-014): the Competitions
    # domain's first real operations, tracking only — same reasoning and
    # naming convention as project.create/.list above.
    _op(
        "competition.create",
        "command",
        "competitions.write",
        True,
        "Track a competition Kang already knows about.",
        schemas=OperationSchemas(
            request=CompetitionCreateRequest, response=CompetitionCreateResponse
        ),
    ),
    _op(
        "competition.list",
        "query",
        "competitions.read",
        False,
        "List every tracked competition, name then id.",
        schemas=OperationSchemas(
            request=CompetitionListRequest, response=CompetitionListResponse
        ),
    ),
    # milestone.create / milestone.list (ADR-015): the Milestones sub-
    # domain's first real operations, tracking only. Scope follows
    # project.*/competition.*'s exact naming convention — milestones.write/
    # milestones.read as their own scope family (not nested under
    # projects.*), matching this session's own established pattern.
    _op(
        "milestone.create",
        "command",
        "milestones.write",
        True,
        "Track a new milestone on a project.",
        schemas=OperationSchemas(
            request=MilestoneCreateRequest, response=MilestoneCreateResponse
        ),
    ),
    _op(
        "milestone.list",
        "query",
        "milestones.read",
        False,
        "List every tracked milestone for one project, due then id.",
        schemas=OperationSchemas(
            request=MilestoneListRequest, response=MilestoneListResponse
        ),
    ),
    # milestone.reach / .miss / .drop (ADR-018): the entity's first status
    # transitions, `pending -> <terminal>`. Same scope as milestone.create
    # (no new authority — a transition is still `milestones.write`).
    # Every command requires an idempotency key (12_API §5), same as
    # task.complete.
    _op(
        "milestone.reach",
        "command",
        "milestones.write",
        True,
        "Mark a milestone reached.",
        schemas=OperationSchemas(
            request=MilestoneTransitionRequest, response=MilestoneTransitionResponse
        ),
    ),
    _op(
        "milestone.miss",
        "command",
        "milestones.write",
        True,
        "Mark a milestone missed.",
        schemas=OperationSchemas(
            request=MilestoneTransitionRequest, response=MilestoneTransitionResponse
        ),
    ),
    _op(
        "milestone.drop",
        "command",
        "milestones.write",
        True,
        "Mark a milestone dropped.",
        schemas=OperationSchemas(
            request=MilestoneTransitionRequest, response=MilestoneTransitionResponse
        ),
    ),
    # goal.create / goal.list (ADR-016): the goal entity's first real
    # operations, tracking only — same reasoning and naming convention as
    # project.create/.list above (self-standing, no required FK, unlike
    # milestone.*). `goals.write`/`goals.read` are new scopes, following
    # the established projects.*/competitions.*/milestones.* family.
    _op(
        "goal.create",
        "command",
        "goals.write",
        True,
        "Track a new goal.",
        schemas=OperationSchemas(
            request=GoalCreateRequest, response=GoalCreateResponse
        ),
    ),
    _op(
        "goal.list",
        "query",
        "goals.read",
        False,
        "List every tracked goal, title then id.",
        schemas=OperationSchemas(request=GoalListRequest, response=GoalListResponse),
    ),
    # goal.achieve / .revise / .retire (ADR-018): the entity's first status
    # transitions, `active -> <terminal>`. Same scope as goal.create (no
    # new authority). Every command requires an idempotency key.
    _op(
        "goal.achieve",
        "command",
        "goals.write",
        True,
        "Mark a goal achieved.",
        schemas=OperationSchemas(
            request=GoalTransitionRequest, response=GoalTransitionResponse
        ),
    ),
    _op(
        "goal.revise",
        "command",
        "goals.write",
        True,
        "Mark a goal revised.",
        schemas=OperationSchemas(
            request=GoalTransitionRequest, response=GoalTransitionResponse
        ),
    ),
    _op(
        "goal.retire",
        "command",
        "goals.write",
        True,
        "Mark a goal retired.",
        schemas=OperationSchemas(
            request=GoalTransitionRequest, response=GoalTransitionResponse
        ),
    ),
    # chat.send (ADR-044): the Chat domain's first operation, and the
    # first real cognitive-agent call anywhere in the system. scope=None
    # is DELIBERATE (ADR-027 D2, not the audit.list/system.health mistake
    # that decision corrected) — first_party_only is what actually gates
    # this, the exact same channel-not-scope shape 05_AGENTS:475 already
    # establishes for held_action.approve/cancel: no agent:{id} principal
    # can ever hold a first-party session, so the channel check alone
    # already closes the gap a scope would otherwise exist to close.
    # idempotent=False: two identical messages may legitimately produce
    # two different model-generated replies — nothing here is a
    # deterministic domain write safely re-playable by key.
    _op(
        "chat.send",
        "command",
        None,
        False,
        "Send one conversational turn to the chat agent; blocks for one model call.",
        channel=OperationChannel(first_party_only=True),
        schemas=OperationSchemas(request=ChatSendRequest, response=ChatSendResponse),
    ),
)
