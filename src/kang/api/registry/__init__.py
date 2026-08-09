"""Operation + event-type + error-code registries — the contract's single
source of truth, served machine-readable.

Layer: api.
Constitutional home: 12_API §16 (`registry.get` serves the machine-readable
registry — operations, schemas, scopes, idempotency class, version,
deprecation — plus the error-code and event-type enums; the registry is the
contract, this document its constitution), 15_EVENT_BUS §6.3 (event-type
registry). Clients and tests verify against THIS, never against prose.

M4 serves the first real operations; the set grows additively (API-005) as
each milestone adds domain surface. Event types mirror the bus registry
(kernel/bus/event_registry) — one vocabulary, imported not re-declared.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from kang.api.errors import ERROR_CODES
from kang.api.schemas.audit import AuditListRequest, AuditListResponse
from kang.api.schemas.competition import (
    CompetitionCreateRequest,
    CompetitionCreateResponse,
    CompetitionListRequest,
    CompetitionListResponse,
)
from kang.api.schemas.deadline import (
    DeadlineCreateRequest,
    DeadlineCreateResponse,
    DeadlineListRequest,
    DeadlineListResponse,
    DeadlineSweepRequest,
    DeadlineSweepResponse,
)
from kang.api.schemas.explain import (
    ExplainInvocationRequest,
    ExplainInvocationResponse,
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
    HeldActionListRequest,
    HeldActionListResponse,
)
from kang.api.schemas.invocation import (
    InvocationListRequest,
    InvocationListResponse,
)
from kang.api.schemas.milestone import (
    MilestoneCreateRequest,
    MilestoneCreateResponse,
    MilestoneListRequest,
    MilestoneListResponse,
    MilestoneTransitionRequest,
    MilestoneTransitionResponse,
)
from kang.api.schemas.notification import (
    NotificationAckRequest,
    NotificationAckResponse,
)
from kang.api.schemas.permission import (
    PermissionListRequest,
    PermissionListResponse,
)
from kang.api.schemas.plan import PlanGenerateRequest, PlanGenerateResponse
from kang.api.schemas.project import (
    ProjectCompleteRequest,
    ProjectCompleteResponse,
    ProjectCreateRequest,
    ProjectCreateResponse,
    ProjectListRequest,
    ProjectListResponse,
)
from kang.api.schemas.system import SystemHealthRequest, SystemHealthResponse
from kang.api.schemas.task import (
    TaskCompleteRequest,
    TaskCompleteResponse,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskGetRequest,
    TaskGetResponse,
)
from kang.kernel.bus.event_registry import EVENT_TYPES as _BUS_EVENT_TYPES

__all__ = [
    "ERROR_CODES",
    "EVENT_TYPES",
    "OPERATIONS",
    "operation",
    "registry_json",
    "registry_snapshot",
]

# One live contract version, additive evolution (API-005).
CONTRACT_VERSION = 1


COMMIT_MODES = ("transactional", "redrive")  # ADR 001 Amendment


@dataclass(frozen=True)
class OperationChannel:
    """ADR 001/002 metadata, bundled to keep `_op` under the size lint's
    parameter limit (11 §4 — beyond a few params, a dataclass).

    `first_party_only` (ADR 002): a channel control, checked by the
    dispatcher after the scope check, independent of `scope` — NOT a
    permission (API-003: no second authorization vocabulary lives here).

    `commit_mode` (ADR 001 Amendment): REQUIRED for every consequential
    command (one that can return `confirmation_required`); `None` for
    everything else. `transactional` — approval-flip and effect commit in
    one kang.db transaction. `redrive` — effect crosses into `adapters/`
    (world-touching); the target adapter MUST have a proven idempotency
    contract before an operation may register with this mode (validated
    below, at import time — not at runtime)."""

    first_party_only: bool = False
    commit_mode: str | None = None


@dataclass(frozen=True)
class OperationSchemas:
    """ADR-010 Ruling 2: Pydantic request/response models, bundled into a
    dataclass for the same reason `OperationChannel` was (11 §4 — beyond a
    few params, a dataclass; keeps `_op` under the size lint's parameter
    limit). Kept as a distinct type from `OperationChannel` rather than
    added as fields on it: `OperationChannel` is ADR-002's precisely-named
    concept for channel control (first_party_only, commit_mode); schemas
    are a different concern (ADR-010), and conflating them would blur a
    boundary ADR-002 was deliberate about.

    `request`/`response` are `None` for operations without an attached
    schema yet (ADR-010 Ruling 3) — the `explain.*` stubs (`explain.
    plan_item`/`notification`/`suggestion`/`memory`) are the last of these
    as of 2026-08-05; `held_action.*` joined the schema-attached set that
    session, alongside `deadline.list`. `registry_snapshot()` serializes
    each to its JSON Schema (`.model_json_schema()`) or explicit `null`;
    the raw Pydantic class stays on `OPERATIONS`/`operation(name)` for
    ADR-010 Ruling 4's dispatch-time validation (`api/dispatch.py::
    _validate_schema`, implemented)."""

    request: type[BaseModel] | None = None
    response: type[BaseModel] | None = None


def _op(
    name: str,
    kind: str,
    scope: str | None,
    idempotent: bool,
    summary: str,
    channel: OperationChannel | None = None,
    schemas: OperationSchemas | None = None,
) -> dict[str, Any]:
    """One operation registry entry (12 §2/§16): name, kind, required scope,
    idempotency class, version-introduced, request/response schema (ADR-010).

    HARD-LIMIT EXCEPTION (11 §4, ADR-010 Ruling 2): `schemas` brings this
    function to 7 parameters, one over the 6-parameter hard limit. Justified:
    bundling `schemas` into `OperationChannel` instead would conflate two
    orthogonal registry concerns ADR-002 (channel control) and ADR-010
    (schema attachment) each deliberately named as distinct — see
    `OperationSchemas`'s own docstring above."""
    channel = channel or OperationChannel()
    schemas = schemas or OperationSchemas()
    if channel.commit_mode is not None and channel.commit_mode not in COMMIT_MODES:
        raise ValueError(f"commit_mode {channel.commit_mode!r} not in {COMMIT_MODES}")
    return {
        "name": name,
        "kind": kind,  # 'command' | 'query'
        "scope": scope,  # required capability, or None (session-only)
        "idempotency": "key-required" if idempotent else "none",
        "version_introduced": "0.1",
        "deprecated": False,
        "summary": summary,
        "first_party_only": channel.first_party_only,
        "commit_mode": channel.commit_mode,
        # Raw type[BaseModel] | None here; registry_snapshot() converts to
        # JSON Schema (ADR-010 Ruling 3).
        "request_schema": schemas.request,
        "response_schema": schemas.response,
    }


# The M4 operation set. Commands carry idempotency keys (API-004); queries
# are freely retryable (API-001).
OPERATIONS: tuple[dict[str, Any], ...] = (
    _op("registry.get", "query", None, False, "Serve this registry."),
    # permission.list (added 2026-08-05, 09_UI §7's System-domain permission
    # screen): scope=None, matching registry.get's own precedent — this
    # serves system metadata about the contract/authority model itself,
    # not a domain resource, so a domain-verb scope would be the wrong
    # vocabulary. Read-only: viewing a grant is not consequential (09_UI §7
    # draws that line at *changing* one, which this operation cannot do).
    _op(
        "permission.list",
        "query",
        None,
        False,
        "List every principal's granted scopes, with plain-language consequences.",
        schemas=OperationSchemas(
            request=PermissionListRequest, response=PermissionListResponse
        ),
    ),
    # task.create / task.get: ADR-010's proof-of-pattern pair (session
    # 2026-07-31) — the first two operations with real request/response
    # schemas attached, chosen as the simplest, most-obviously-typed params
    # among the currently-wired operations. The other 12 entries below are
    # deliberately untouched (schemas default to None); rolling the pattern
    # out to them is follow-up work, per ADR-010's Consequences.
    _op(
        "task.create",
        "command",
        "task.write",
        True,
        "Create a task.",
        schemas=OperationSchemas(
            request=TaskCreateRequest, response=TaskCreateResponse
        ),
    ),
    _op(
        "task.get",
        "query",
        "task.read",
        False,
        "Fetch a task by id.",
        schemas=OperationSchemas(request=TaskGetRequest, response=TaskGetResponse),
    ),
    # task.complete (added 2026-08-09): the task entity's first status-
    # transition operation, same scope as task.create (05 §9's own
    # "task.write" naming for this entity — not the tasks.write plural
    # kernel:scheduler already holds; that's a pre-existing naming
    # inconsistency between the scheduler's own grant and this entity's
    # registered scope, noted here rather than silently reconciled).
    # Every command MUST carry an idempotency key (12_API §5, no
    # exceptions carved out) — a retried "complete" click must not risk
    # double-processing, same as every other command here.
    _op(
        "task.complete",
        "command",
        "task.write",
        True,
        "Mark a task done.",
        schemas=OperationSchemas(
            request=TaskCompleteRequest, response=TaskCompleteResponse
        ),
    ),
    # Deadlines (M5). Scope names follow 05 §9's domain-verb vocabulary
    # (`deadlines.set`, `deadlines.mark_alerted`), not a new one. Neither is
    # consequential — 05 Appendix D's closed list does not name them — so
    # neither declares a commit_mode (ADR-001 Amendment).
    _op(
        "deadline.create",
        "command",
        "deadlines.set",
        True,
        "Track a deadline.",
        schemas=OperationSchemas(
            request=DeadlineCreateRequest, response=DeadlineCreateResponse
        ),
    ),
    _op(
        "deadline.sweep",
        "command",
        "deadlines.mark_alerted",
        True,
        "Alert every tracked deadline whose lead threshold has been crossed.",
        schemas=OperationSchemas(
            request=DeadlineSweepRequest, response=DeadlineSweepResponse
        ),
    ),
    # deadline.list: added 2026-08-05 for the dashboard's Zone 2 (09_UI §4).
    # `deadlines.read` follows `task.read`'s exact naming pattern (05 §9
    # domain-verb vocabulary) — a query scope, not a new kind of scope.
    # Exposes DeadlineStore.active(), which already existed and was already
    # used internally by deadline_sweep and plan.generate; no new domain
    # logic, no ADR trigger (12_API §16: "the set grows additively as each
    # milestone adds domain surface").
    _op(
        "deadline.list",
        "query",
        "deadlines.read",
        False,
        "List every tracked deadline, soonest first.",
        schemas=OperationSchemas(
            request=DeadlineListRequest, response=DeadlineListResponse
        ),
    ),
    # plan.generate (FR-001): the deterministic morning plan. Scope follows
    # 05 §9's domain-verb vocabulary (`tasks.*` — it stamps plan_date on
    # tasks). Not consequential (05 Appendix D's closed list), so no
    # commit_mode.
    _op(
        "plan.generate",
        "command",
        "tasks.write",
        True,
        "Generate the deterministic daily plan from P0 data (zero models).",
        schemas=OperationSchemas(
            request=PlanGenerateRequest, response=PlanGenerateResponse
        ),
    ),
    # notification.ack (12 §13). No capability scope: no scope vocabulary
    # for acking exists in the docs, and inventing one would be vocabulary
    # creation (11 §3). It is instead first-party-only (ADR-002) for the
    # same reason held_action.* is — a plugin draining Kang's notification
    # queue is out-of-mandate regardless of risk, and auto-acking his
    # time-sensitive alerts before he sees them is a denial of service.
    _op(
        "notification.ack",
        "command",
        None,
        True,
        "Acknowledge a notification (additive; never deletes history).",
        channel=OperationChannel(first_party_only=True),
        schemas=OperationSchemas(
            request=NotificationAckRequest, response=NotificationAckResponse
        ),
    ),
    _op(
        "explain.invocation",
        "query",
        None,
        False,
        "Reconstruct an invocation from permanent storage by correlation_id.",
        schemas=OperationSchemas(
            request=ExplainInvocationRequest, response=ExplainInvocationResponse
        ),
    ),
    _op("explain.plan_item", "query", None, False, "Explain a plan item."),
    _op("explain.notification", "query", None, False, "Explain a notification."),
    _op("explain.suggestion", "query", None, False, "Explain a suggestion."),
    _op("explain.memory", "query", None, False, "Explain a memory record."),
    # held_action.* (ADR 001, ADR 002): channel-gated, not scope-gated — no
    # `kang`-only scope exists for these (API-003/SEC-004: first-party-only
    # is a channel, never a grant). Handlers wired 2026-08-05
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
    # audit.list / system.health: added 2026-08-05 for the System domain's
    # Activity and Health views (09_UI §12). Both scope=None, matching
    # registry.get/permission.list's own precedent — system metadata about
    # the Core itself, not a domain resource a domain-verb scope would fit.
    _op(
        "audit.list",
        "query",
        None,
        False,
        "List every audit record of one month, oldest first.",
        schemas=OperationSchemas(request=AuditListRequest, response=AuditListResponse),
    ),
    _op(
        "system.health",
        "query",
        None,
        False,
        "List every scheduled job's status and whether automation is paused.",
        schemas=OperationSchemas(
            request=SystemHealthRequest, response=SystemHealthResponse
        ),
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
        None,
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
)

# ADR 001 Amendment's registration-time gate: an operation MUST NOT declare
# commit_mode="redrive" until its target adapter has a proven idempotency
# contract + conformance test. No such adapter exists yet (M4) — this loop
# is the enforcement point for when one first tries to register.
for _entry in OPERATIONS:
    if _entry["commit_mode"] == "redrive":
        raise NotImplementedError(
            f"{_entry['name']}: commit_mode='redrive' requires a proven "
            "adapter idempotency contract + conformance test before "
            "registration (ADR 001 Amendment) — none exist yet at M4"
        )

# Event types are the bus vocabulary (12 §6: the API adds no second event
# language) — served here as records for client subscription.
EVENT_TYPES: tuple[dict[str, Any], ...] = tuple(
    {
        "name": event_type.name,
        "category": event_type.category,
        "recovery_grade": event_type.recovery_grade,
        "plugin_visible": event_type.plugin_visible,
        "type_version": event_type.type_version,
    }
    for event_type in _BUS_EVENT_TYPES.values()
)

_OPERATION_INDEX = {entry["name"]: entry for entry in OPERATIONS}


def operation(name: str) -> dict[str, Any] | None:
    """The registry entry for an operation name, or None if unregistered."""
    return _OPERATION_INDEX.get(name)


def _json_safe_operation(entry: dict[str, Any]) -> dict[str, Any]:
    """`OPERATIONS` carries the raw Pydantic class in `request_schema`/
    `response_schema` (so `operation(name)` can hand it to ADR-010 Ruling
    4's future dispatch-time validator) — `type[BaseModel]` is not
    JSON-serializable, so the served/snapshot form (ADR-010 Ruling 3)
    converts each to its `.model_json_schema()` dict, or explicit `None`
    when unattached."""
    safe = dict(entry)
    for key in ("request_schema", "response_schema"):
        model = safe.get(key)
        safe[key] = model.model_json_schema() if model is not None else None
    return safe


def registry_snapshot() -> dict[str, Any]:
    """The full registry as one deterministic document (what `registry.get`
    returns)."""
    return {
        "contract_version": CONTRACT_VERSION,
        "operations": [_json_safe_operation(entry) for entry in OPERATIONS],
        "event_types": list(EVENT_TYPES),
        "error_codes": list(ERROR_CODES),
    }


def registry_json() -> str:
    """The registry serialized as canonical JSON (sorted keys — byte-stable
    for the conformance diff gate, 13 §2.4)."""
    return json.dumps(registry_snapshot(), sort_keys=True, ensure_ascii=False)
