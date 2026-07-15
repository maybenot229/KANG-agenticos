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
from typing import Any

from kang.api.errors import ERROR_CODES
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


def _op(
    name: str,
    kind: str,
    scope: str | None,
    idempotent: bool,
    summary: str,
) -> dict[str, Any]:
    """One operation registry entry (12 §2/§16): name, kind, required scope,
    idempotency class, version-introduced. Schemas harden as domain grows."""
    return {
        "name": name,
        "kind": kind,  # 'command' | 'query'
        "scope": scope,  # required capability, or None (session-only)
        "idempotency": "key-required" if idempotent else "none",
        "version_introduced": "0.1",
        "deprecated": False,
        "summary": summary,
    }


# The M4 operation set. Commands carry idempotency keys (API-004); queries
# are freely retryable (API-001).
OPERATIONS: tuple[dict[str, Any], ...] = (
    _op("registry.get", "query", None, False, "Serve this registry."),
    _op("task.create", "command", "task.write", True, "Create a task."),
    _op("task.get", "query", "task.read", False, "Fetch a task by id."),
    _op(
        "explain.invocation",
        "query",
        None,
        False,
        "Reconstruct an invocation from permanent storage by correlation_id.",
    ),
    _op("explain.plan_item", "query", None, False, "Explain a plan item."),
    _op("explain.notification", "query", None, False, "Explain a notification."),
    _op("explain.suggestion", "query", None, False, "Explain a suggestion."),
    _op("explain.memory", "query", None, False, "Explain a memory record."),
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


def registry_snapshot() -> dict[str, Any]:
    """The full registry as one deterministic document (what `registry.get`
    returns)."""
    return {
        "contract_version": CONTRACT_VERSION,
        "operations": list(OPERATIONS),
        "event_types": list(EVENT_TYPES),
        "error_codes": list(ERROR_CODES),
    }


def registry_json() -> str:
    """The registry serialized as canonical JSON (sorted keys — byte-stable
    for the conformance diff gate, 13 §2.4)."""
    return json.dumps(registry_snapshot(), sort_keys=True, ensure_ascii=False)
