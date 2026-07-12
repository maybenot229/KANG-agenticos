"""Operation + event-type + error-code registries — the contract's single
source of truth, served machine-readable.

Layer: api.
Constitutional home: 12_API §16 (`registry.get` serves the machine-readable
registry; clients are verified against it, never against prose);
15_EVENT_BUS §6.3 (event-type registry). Registries are empty at M0 by
design — nothing exists in the product that does not exist here first, and
nothing exists yet. Operations arrive with M4; event types with M2. The
registry diff gate (removals without deprecation fail) arms at M4.
"""

from __future__ import annotations

import json
from typing import Any

__all__ = [
    "ERROR_CODES",
    "EVENT_TYPES",
    "OPERATIONS",
    "registry_json",
    "registry_snapshot",
]

# One live contract version, additive evolution (API-005).
CONTRACT_VERSION = 1

# Registry-closed enums. Entries are declarative records (schema, scopes,
# idempotency class — 12 §16); the record shapes harden when the first real
# entry lands at M2/M4.
OPERATIONS: tuple[dict[str, Any], ...] = ()
EVENT_TYPES: tuple[dict[str, Any], ...] = ()
ERROR_CODES: tuple[dict[str, Any], ...] = ()


def registry_snapshot() -> dict[str, Any]:
    """The full registry as one deterministic document (what `registry.get`
    returns once the API layer exists at M4)."""
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
