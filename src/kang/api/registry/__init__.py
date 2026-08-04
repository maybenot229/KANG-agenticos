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
from kang.api.schemas.deadline import (
    DeadlineCreateRequest,
    DeadlineCreateResponse,
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
from kang.api.schemas.plan import PlanGenerateRequest, PlanGenerateResponse
from kang.api.schemas.task import (
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
    schema yet (ADR-010 Ruling 3) — including both currently-unimplemented
    `held_action.*` operations and every operation not yet rolled out under
    this ADR. `registry_snapshot()` serializes each to its JSON Schema
    (`.model_json_schema()`) or explicit `null`; the raw Pydantic class
    stays on `OPERATIONS`/`operation(name)` for ADR-010 Ruling 4's future
    dispatch-time validation use (not implemented this session — see the
    session report)."""

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
    # is a channel, never a grant). Handlers are not yet wired into the
    # composition root (no held-action feature is live end-to-end); these
    # entries register the contract shape ahead of that wiring, per 17 §4's
    # "ports/registry first" ordering discipline.
    _op(
        "held_action.approve",
        "command",
        None,
        True,
        "Approve a pending held action; drives its effect per commit_mode.",
        channel=OperationChannel(first_party_only=True),
    ),
    _op(
        "held_action.cancel",
        "command",
        None,
        True,
        "Decline a pending held action.",
        channel=OperationChannel(first_party_only=True),
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
