"""Event log port — the EB-005 envelope and the append/confirm surface.

Layer: domain/ports (both sides of the firewall consume the envelope).
Constitutional home: 15_EVENT_BUS §5.1 (envelope: normative, CLOSED field
list; additive evolution only), §4 (pending → confirmed | orphaned write
order), EB-003 (recovery_grade denormalized into each row so the log is
self-describing during recovery — recovery cannot depend on kang.db).
Delivery machinery (cursors, retries, dead letters) is M2's subject; this
port carries only what truth-durability needs at M1.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

__all__ = [
    "EnvelopeValidationError",
    "EventEnvelope",
    "EventLog",
    "EventNotFoundError",
    "PROVENANCES",
    "StoredEvent",
    "validate_envelope",
]

PROVENANCES = ("kang", "derived", "external_untrusted")

# noun.verb_past_tense, optionally namespaced (plugin.{id}.*) — EB-001/§5.1.
_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


class EnvelopeValidationError(Exception):
    """The envelope violates §5.1. Publish validation failure is bug-level:
    rejected before it enters the log (15 §13)."""


class EventNotFoundError(Exception):
    """No event with the given seq exists."""


@dataclass(frozen=True)
class EventEnvelope:
    """The §5.1 envelope minus log-assigned fields (seq, recorded_at,
    state — those belong to the stored row, not the publisher)."""

    event_id: str
    type: str
    occurred_at: str  # ISO-8601, injected clock
    principal: str
    correlation_id: str
    device_id: str
    payload: dict[str, Any]
    provenance: str = "kang"
    recovery_grade: bool = False
    type_version: int = 1
    causation_id: str | None = None
    entity_refs: tuple[dict[str, str], ...] = field(default_factory=tuple)


def _require_non_empty(envelope: EventEnvelope) -> None:
    for name in ("event_id", "occurred_at", "principal", "correlation_id", "device_id"):
        if not getattr(envelope, name):
            raise EnvelopeValidationError(f"envelope field {name!r} must be non-empty")


def validate_envelope(envelope: EventEnvelope) -> None:
    """Enforce the §5.1 closed field list's value rules. Registry-closed
    type admission (§6.3) arrives with the bus at M2; shape rules bind now."""
    _require_non_empty(envelope)
    if not _TYPE_RE.match(envelope.type):
        raise EnvelopeValidationError(
            f"type {envelope.type!r} is not noun.verb_past_tense-shaped (EB-001)"
        )
    if envelope.provenance not in PROVENANCES:
        raise EnvelopeValidationError(
            f"provenance {envelope.provenance!r} not in {PROVENANCES}"
        )
    if envelope.type_version < 1:
        raise EnvelopeValidationError("type_version must be >= 1")
    if not isinstance(envelope.payload, dict):
        raise EnvelopeValidationError("payload must be a JSON object")
    for ref in envelope.entity_refs:
        if set(ref) != {"kind", "id"} or not ref["kind"] or not ref["id"]:
            raise EnvelopeValidationError(
                f"entity_refs items are {{kind, id}}, got {ref!r}"
            )
    if envelope.recovery_grade and not envelope.payload:
        raise EnvelopeValidationError(
            "a recovery-grade payload must be self-sufficient for "
            "re-application, not empty (EB-003)"
        )


@dataclass(frozen=True)
class StoredEvent:
    """A row of the log: the envelope plus log-assigned truth."""

    seq: int
    envelope: EventEnvelope
    recorded_at: str
    state: str  # 'pending' | 'confirmed' | 'orphaned' (§4)


class EventLog(Protocol):
    """The write-ahead event log (synchronous=FULL — its redo duty).

    Implementations: SqliteEventLog (adapters/eventlog), FakeEventLog
    (adapters/fakes) — contract-paired (13 §2.3)."""

    def append(self, envelope: EventEnvelope) -> int:
        """Validate, append as pending, return the assigned seq (EB-004
        step 2 — before the state commit, always)."""
        ...

    def confirm(self, seq: int) -> None:
        """Mark confirmed (EB-004 step 4)."""
        ...

    def mark_orphaned(self, seq: int) -> None:
        """Reconciliation verdict for an unconfirmable informational event:
        never delivered, never deleted, surfaced (§4.3)."""
        ...

    def pending(self) -> list[StoredEvent]:
        """All pending events, oldest first — the reconciliation window."""
        ...

    def read_from(self, seq_exclusive: int) -> list[StoredEvent]:
        """Events with seq greater than the watermark, oldest first —
        the snapshot gap-fill source (EB-009 form 2) and the per-subscriber
        delivery source (EB-007)."""
        ...

    def find_by_event_id(self, event_id: str) -> StoredEvent | None:
        """The event with this id, or None — the substrate the runtime
        causation-depth guard walks (EB-011.2)."""
        ...

    def last_seq(self) -> int:
        """Highest assigned seq (0 when empty) — the snapshot watermark."""
        ...
