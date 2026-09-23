"""memory.update / .pin / .archive / .restore / .delete /
.restore_from_snapshot handlers — the record lifecycle and the deletion
covenant (ADR-053).

Layer: api. Handlers orchestrate: fetch, guard, publish-or-gate; no
persistence decision lives here that `MemoryStore`/`BackupService` do not
also enforce (defence in depth — the same discipline `write_gate.py`
documents for its own callers).
Constitutional home: 06_MEMORY Part III/M-002 (the transition table —
`memory.delete` requires `archived`; M-002 has no `active` -> `deleted`
edge), §7.2 verbatim (the recovery window and its honest limit, D6), §8.2
(edits never overwrite silently), §12.3 (every transition and every
deletion audited, with its policy citation), 12_API §10, ADR-021 (the
consequential machinery `memory.delete` uses), ADR-053 D1-D7.

Four operations (`update`/`pin`/`archive`/`restore`) publish `memory.updated`
under the event-before-commit pairing (EB-004), mirroring
`goal_ops._make_goal_transition_handler`'s exact shape: a pure preview of
the resulting row is what gets published; the store's own guarded write —
run inside `commit_state` — is the only thing that actually persists, and
its `MemoryConflict` is what `bus.publish` propagates on a stale guard.

`memory.delete` never publishes (D6 Consequences: no consumer, and a
replayed delete after a snapshot restore would silently re-delete the
just-restored record) — it is durable through its own transaction alone,
gated by `require_confirmation`/`held_action.approve`'s transactional
driver (`make_memory_delete_effect` is what composition.py's
`transactional_effects` table points `memory.delete` at).

`memory.restore_from_snapshot` never publishes either (a file-based
recovery mechanism entirely inside `BackupService`, not an ordinary
write) and is not consequential — no held action, no confirmation; D5
names no such gate.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable

from kang.api.dispatch import Handler, HandlerContext
from kang.api.errors import ApiError
from kang.api.operations.consequential import (
    ConfirmationDeps,
    ConfirmationRequest,
    require_confirmation,
)
from kang.api.operations.memory_ops import MEMORY_PRINCIPAL
from kang.domain.memory import memory_event_payload
from kang.domain.ports.backup import BackupService
from kang.domain.ports.clock import Clock
from kang.domain.ports.eventlog import EventEnvelope
from kang.domain.ports.memory_store import (
    ContentEdit,
    MemoryConflict,
    MemoryRecord,
    MemoryStore,
)
from kang.kernel.audit.service import AuditService
from kang.kernel.bus.bus import EventBus

__all__ = [
    "DELETE_REVERSIBILITY",
    "MemoryLifecycleDeps",
    "make_memory_delete_effect",
    "make_memory_lifecycle_handlers",
]

# ADR-053 D6, verbatim in substance from 06 §7.2. The second sentence is an
# honest limit, not a reassurance — do not soften it (build brief §3).
DELETE_REVERSIBILITY = (
    "This record can be restored from a daily snapshot for 30 days after "
    "deletion; after that, KANG cannot undelete it. The deleted content "
    "nevertheless remains inside existing backup snapshots until the last "
    "one containing it rotates out, which can take up to twelve months — "
    "deletion from KANG is not destruction from your backups."
)

# 09_UI §7's dialog: enough to recognise, not the whole record.
_ACTION_CONTENT_PREVIEW = 200


@dataclass(frozen=True)
class MemoryLifecycleDeps:
    """Everything the six lifecycle handlers are built from (11 §4)."""

    bus: EventBus
    memory: MemoryStore
    backups: BackupService
    confirmation: ConfirmationDeps
    audit: AuditService
    clock: Clock
    new_id: Callable[[], str]
    device_id: str


def _updated_envelope(
    deps: MemoryLifecycleDeps, context: HandlerContext, record: MemoryRecord
) -> EventEnvelope:
    return EventEnvelope(
        event_id=deps.new_id(),
        type="memory.updated",
        occurred_at=record.updated_at,
        principal=MEMORY_PRINCIPAL,
        correlation_id=context.correlation_id,
        device_id=deps.device_id,
        payload=memory_event_payload(record),
        recovery_grade=True,
        entity_refs=({"kind": "memory", "id": record.id},),
    )


def _audit(
    deps: MemoryLifecycleDeps, context: HandlerContext, action: str, **details: Any
) -> None:
    deps.audit.record(
        context.principal, action, details, correlation_id=context.correlation_id
    )


def _get_or_404(deps: MemoryLifecycleDeps, record_id: str) -> MemoryRecord:
    record = deps.memory.get(record_id)
    if record is None:
        raise ApiError("not_found", f"no such memory record {record_id!r}")
    return record


def _make_update_handler(deps: MemoryLifecycleDeps) -> Handler:
    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        record_id = params["id"]
        current = _get_or_404(deps, record_id)
        if current.status != "active":
            raise ApiError(
                "conflict",
                f"memory record {record_id} is {current.status!r}, not active",
            )
        expected_revision = params["expected_revision"]
        if current.revision != expected_revision:
            raise ApiError(
                "conflict",
                f"memory record {record_id}: expected revision "
                f"{expected_revision}, store has {current.revision}",
            )
        now = deps.clock.now().isoformat()
        content, reason = params["content"], params["reason"]
        preview = replace(
            current,
            content=content,
            reason=reason,
            revision=current.revision + 1,
            updated_at=now,
            device_id=deps.device_id,
        )
        committed: list[MemoryRecord] = []

        def _commit() -> None:
            committed.append(
                deps.memory.update_content(
                    ContentEdit(
                        record_id=record_id,
                        content=content,
                        reason=reason,
                        expected_revision=expected_revision,
                        edited_by=context.principal,
                        device_id=deps.device_id,
                        now=now,
                    )
                )
            )

        try:
            deps.bus.publish(
                _updated_envelope(deps, context, preview), commit_state=_commit
            )
        except MemoryConflict as exc:
            raise ApiError("conflict", str(exc)) from exc
        result = committed[0]
        _audit(deps, context, "memory.updated", id=result.id, revision=result.revision)
        return {"id": result.id, "revision": result.revision}

    return handler


def _make_pin_handler(deps: MemoryLifecycleDeps) -> Handler:
    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        record_id = params["id"]
        current = _get_or_404(deps, record_id)
        now = deps.clock.now().isoformat()
        pinned = params["pinned"]
        preview = replace(
            current,
            pinned=pinned,
            revision=current.revision + 1,
            updated_at=now,
            device_id=deps.device_id,
        )
        committed: list[MemoryRecord] = []

        def _commit() -> None:
            committed.append(
                deps.memory.set_pinned(record_id, pinned, deps.device_id, now)
            )

        try:
            deps.bus.publish(
                _updated_envelope(deps, context, preview), commit_state=_commit
            )
        except MemoryConflict as exc:
            raise ApiError("not_found", str(exc)) from exc
        result = committed[0]
        _audit(deps, context, "memory.updated", id=result.id, revision=result.revision)
        return {"id": result.id, "revision": result.revision, "pinned": result.pinned}

    return handler


def _make_transition_handler(
    deps: MemoryLifecycleDeps, expected_status: str, new_status: str
) -> Handler:
    """`memory.archive` (`active` -> `archived`) / `memory.restore`
    (`archived` -> `active`) — ADR-053 D3."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        record_id = params["id"]
        current = _get_or_404(deps, record_id)
        if current.status != expected_status:
            raise ApiError(
                "conflict",
                f"memory record {record_id} is {current.status!r}, not "
                f"{expected_status!r}",
            )
        now = deps.clock.now().isoformat()
        preview = replace(
            current,
            status=new_status,
            revision=current.revision + 1,
            updated_at=now,
            device_id=deps.device_id,
        )
        committed: list[MemoryRecord] = []

        def _commit() -> None:
            committed.append(
                deps.memory.transition_status(
                    record_id, expected_status, new_status, deps.device_id, now
                )
            )

        try:
            deps.bus.publish(
                _updated_envelope(deps, context, preview), commit_state=_commit
            )
        except MemoryConflict as exc:
            raise ApiError("conflict", str(exc)) from exc
        result = committed[0]
        _audit(deps, context, "memory.updated", id=result.id, revision=result.revision)
        return {"id": result.id, "revision": result.revision, "status": result.status}

    return handler


def make_memory_delete_effect(
    memory: MemoryStore, audit: AuditService, clock: Clock
) -> Callable[[dict[str, Any]], None]:
    """The `transactional_effects` entry `memory.delete` resolves to
    (ADR-021's machinery; ADR-053 D4). Runs inside `held_action.approve`'s
    already-open transaction — see `MemoryStore.delete_and_tombstone_in_txn`'s
    own docstring. Audited here, with the policy citation (06 §12.3) —
    the dispatcher's own generic `held_action.approve.dispatched`/`.ok`
    audit entries name neither the record nor the policy."""

    def effect(params: dict[str, Any]) -> None:
        now = clock.now().isoformat()
        record_id, deleted_by = params["record_id"], params["deleted_by"]
        try:
            memory.delete_and_tombstone_in_txn(record_id, deleted_by, now)
        except MemoryConflict as exc:
            raise ApiError("conflict", str(exc)) from exc
        audit.record(
            deleted_by,
            "memory.deleted",
            {"id": record_id, "policy_ref": "kang:explicit"},
        )

    return effect


def _make_delete_handler(deps: MemoryLifecycleDeps) -> Handler:
    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        record_id = params["id"]
        current = _get_or_404(deps, record_id)
        if current.status != "archived":
            raise ApiError(
                "conflict",
                f"memory record {record_id} is {current.status!r}; only an "
                "archived record may be deleted (M-002 has no active -> "
                "deleted edge)",
            )
        snippet = current.content[:_ACTION_CONTENT_PREVIEW]
        require_confirmation(
            deps.confirmation,
            context,
            ConfirmationRequest(
                operation="memory.delete",
                action=f"Delete memory record {record_id}: {snippet!r}",
                reason=params["reason"],
                reversibility=DELETE_REVERSIBILITY,
                params={"record_id": record_id, "deleted_by": context.principal},
            ),
        )

    return handler


def _make_restore_from_snapshot_handler(deps: MemoryLifecycleDeps) -> Handler:
    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        record_id = params["id"]
        now = deps.clock.now().isoformat()
        outcome = deps.backups.restore_memory_record(record_id, now, deps.device_id)
        if outcome.outcome == "conflict":
            raise ApiError(
                "conflict", f"a live memory record {record_id} already exists"
            )
        if outcome.outcome == "not_found":
            raise ApiError(
                "not_found",
                f"memory record {record_id} cannot be restored from a daily "
                "snapshot (06 §7.2: not offered past the 30-day window)",
            )
        _audit(
            deps,
            context,
            "memory.restored_from_snapshot",
            id=outcome.id,
            snapshot=outcome.snapshot,
        )
        return {
            "id": outcome.id,
            "revision": outcome.revision,
            "snapshot": outcome.snapshot,
        }

    return handler


def make_memory_lifecycle_handlers(deps: MemoryLifecycleDeps) -> dict[str, Handler]:
    """The six operations, keyed by name."""
    return {
        "memory.update": _make_update_handler(deps),
        "memory.pin": _make_pin_handler(deps),
        "memory.archive": _make_transition_handler(deps, "active", "archived"),
        "memory.restore": _make_transition_handler(deps, "archived", "active"),
        "memory.delete": _make_delete_handler(deps),
        "memory.restore_from_snapshot": _make_restore_from_snapshot_handler(deps),
    }
