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

The `_op(...)` literal itself — `OPERATIONS`, `OperationChannel`,
`OperationSchemas`, every schema import it needs — lives in
`kang.api.registry.operations`, split out 2026-09-13 (ADR-034) once the
operation set crossed the size lint's line limit here. `OPERATIONS` is
re-exported below so every external caller's import path
(`from kang.api.registry import OPERATIONS`) is unchanged.
"""

from __future__ import annotations

import json
from typing import Any

from kang.api.errors import ERROR_CODES
from kang.api.registry.operations import OPERATIONS
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
