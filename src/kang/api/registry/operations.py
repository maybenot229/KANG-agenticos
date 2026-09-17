"""The operation registry literal, part 1 of 2 — every `_op(...)` entry
up through `explain.*` (12_API §16).

Layer: api.
Constitutional home: same as `kang.api.registry`'s own module docstring;
split out purely to keep that file under the size lint's line limit
(11 §4) once the operation set crossed it (2026-09-13, ADR-034's
`backup.offsite_check`) — not a domain concept of its own, and not a new
layer: `kang.api.registry` still owns `registry_snapshot`/`operation`/
the event-type and error-code passthrough.

Split again into two files (2026-09-17, ADR-047's `conversation.list`/
`message.list` pair crossed 800 lines here) — same reasoning, still not
a domain concept of its own: `OperationChannel`/`OperationSchemas`/`_op`
stay here since `operations_ext.py` needs them; the tuple itself splits
at the `explain.*`/`held_action.*` boundary (already a clean seam in the
existing entry order) purely because that is roughly the midpoint, not
because the two halves mean anything different. `kang.api.registry`'s
own `__init__.py` concatenates both tuples into the one `OPERATIONS`
every external caller already imports — unchanged path, unchanged
contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from kang.api.schemas.conversation import (
    ConversationListRequest,
    ConversationListResponse,
    ConversationPurgeRequest,
    ConversationPurgeResponse,
    MessageListRequest,
    MessageListResponse,
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
from kang.api.schemas.notification import (
    NotificationAckRequest,
    NotificationAckResponse,
)
from kang.api.schemas.permission import (
    PermissionListRequest,
    PermissionListResponse,
)
from kang.api.schemas.plan import PlanGenerateRequest, PlanGenerateResponse
from kang.api.schemas.task import (
    TaskCompleteRequest,
    TaskCompleteResponse,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskGetRequest,
    TaskGetResponse,
)

__all__ = ["COMMIT_MODES", "OperationChannel", "OperationSchemas", "OPERATIONS", "_op"]

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
    # registry.get stays scope=None DELIBERATELY (ADR-027 D2): it serves the
    # contract a client must read before it can call anything — including to
    # learn which scopes exist — so gating it behind a capability is circular.
    # It leaks shape, never state. One of only three unscoped operations; a
    # test locks that set closed (unit/kang/api/registry/test_registry.py),
    # because `_authorize` SKIPS the engine for scope=None rather than
    # default-denying, so a careless fourth would be reachable by any
    # authenticated principal.
    _op("registry.get", "query", None, False, "Serve this registry."),
    # permission.list (added 2026-08-05, 09_UI §7's System-domain permission
    # screen): serves system metadata about the contract/authority model
    # itself. Registered scope=None originally, on registry.get's precedent.
    # Read-only: viewing a grant is not consequential (09_UI §7 draws that
    # line at *changing* one, which this operation cannot do). SCOPED as of
    # ADR-027 (`permissions.read`) — the grant snapshot is a map of the
    # authority surface, which is exactly what an injected agent would read
    # first; `registry.get`'s unscoped precedent does not extend to it.
    _op(
        "permission.list",
        "query",
        "permissions.read",
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
    # ADR-047: memory_steward's own first real tool — purges conversation
    # transcripts past CONVERSATION_RETENTION_DAYS (90d, 06_MEMORY §7.1).
    _op(
        "conversation.purge",
        "command",
        "conversations.purge",
        True,
        "Purge conversation transcripts past the retention threshold.",
        schemas=OperationSchemas(
            request=ConversationPurgeRequest, response=ConversationPurgeResponse
        ),
    ),
    # conversation.list / message.list: added 2026-09-17, 02_PRODUCT_
    # REQUIREMENTS.md:697's "Conversation history" system view.
    # `conversations.read` follows `deadlines.read`'s exact naming
    # pattern (domain-verb vocabulary) — a query scope, not a new kind
    # of scope; one scope covers both operations, the same "one family,
    # one read scope" shape `backups.read` already uses. Pure exposure
    # of `ConversationStore.list_recent`/`.recent_messages` — no new
    # domain logic, mechanical extensions of an established pattern
    # (no ADR triggered, matching every other `.list` operation before
    # them).
    _op(
        "conversation.list",
        "query",
        "conversations.read",
        False,
        "List the most recently active conversations.",
        schemas=OperationSchemas(
            request=ConversationListRequest, response=ConversationListResponse
        ),
    ),
    _op(
        "message.list",
        "query",
        "conversations.read",
        False,
        "List the messages in one named conversation, oldest first.",
        schemas=OperationSchemas(
            request=MessageListRequest, response=MessageListResponse
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
        "notifications.ack",
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
        "explain.read",
        False,
        "Reconstruct an invocation from permanent storage by correlation_id.",
        schemas=OperationSchemas(
            request=ExplainInvocationRequest, response=ExplainInvocationResponse
        ),
    ),
    _op("explain.plan_item", "query", "explain.read", False, "Explain a plan item."),
    _op(
        "explain.notification",
        "query",
        "explain.read",
        False,
        "Explain a notification.",
    ),
    _op("explain.suggestion", "query", "explain.read", False, "Explain a suggestion."),
    _op("explain.memory", "query", "explain.read", False, "Explain a memory record."),
)
