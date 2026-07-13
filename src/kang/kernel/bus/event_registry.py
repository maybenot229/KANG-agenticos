"""Event-type registry — the closed taxonomy of publishable facts.

Layer: kernel/bus (the bus is the enforcement point: publishing an
unregistered type is rejected at validation — §6.3). The API serves this
registry alongside the Operation Registry (12_API §16) by importing it
(api → kernel is legal, 17 §4.2); the kernel cannot import the api, so the
registry's truth lives here, at the validator.
Constitutional home: 15_EVENT_BUS EB-006 §6.1 (closed taxonomy; additions
require an ADR, like Memory's type list), §6.3 (every type carries a
schema, recovery_grade, plugin-visible flag; recovery-grade types owe a
payload-sufficiency test — 13 §16.2), EB-003 (recovery_grade contract).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from kang.domain.ports.eventlog import EventEnvelope

__all__ = [
    "EVENT_TYPES",
    "EventType",
    "UnregisteredEventTypeError",
    "is_recovery_grade",
    "require_registered",
    "validate_registration",
]

CATEGORIES = ("domain", "system", "lifecycle", "integration", "plugin", "notification")

# Self-sufficient payload for a task truth mutation (EB-003): the full field
# set, so a lost write replays exactly. Mirrors 07 §5.2's task columns.
_TASK_PAYLOAD_FIELDS = (
    "id",
    "project_id",
    "title",
    "notes",
    "status",
    "priority",
    "due",
    "plan_date",
    "estimate_min",
    "actual_min",
    "completed_at",
    "created_at",
    "updated_at",
    "device_id",
    "revision",
)


class UnregisteredEventTypeError(Exception):
    """A type not in the closed taxonomy was offered for publication (§6.3):
    bug-level, rejected before it can enter the log."""


@dataclass(frozen=True)
class EventType:
    """One registry entry (§6.3). `required_payload_fields` is M2's
    lightweight schema — presence-checked at publish; a richer schema
    language arrives with the operation registry's at M4."""

    name: str
    category: str
    recovery_grade: bool
    plugin_visible: bool
    version_introduced: str
    type_version: int = 1
    required_payload_fields: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValueError(f"category {self.category!r} not in {CATEGORIES}")


# The closed set. At M2 the truth that exists is the task entity's; each
# addition is an ADR (§6.1). Task mutations are Domain + recovery-grade
# (EB-006 §6.1: "Domain — mostly yes").
_TYPES: tuple[EventType, ...] = (
    EventType(
        name="task.created",
        category="domain",
        recovery_grade=True,
        plugin_visible=True,
        version_introduced="0.1",
        required_payload_fields=_TASK_PAYLOAD_FIELDS,
    ),
    EventType(
        name="task.updated",
        category="domain",
        recovery_grade=True,
        plugin_visible=True,
        version_introduced="0.1",
        required_payload_fields=_TASK_PAYLOAD_FIELDS,
    ),
)

EVENT_TYPES: dict[str, EventType] = {
    event_type.name: event_type for event_type in _TYPES
}


def require_registered(type_name: str) -> EventType:
    """Return the registry entry or reject — the §6.3 admission rule."""
    entry = EVENT_TYPES.get(type_name)
    if entry is None:
        raise UnregisteredEventTypeError(
            f"event type {type_name!r} is not registered (§6.3); publishing "
            "an unregistered type is a bug-level failure"
        )
    return entry


def is_recovery_grade(type_name: str) -> bool:
    """Recovery-grade classification, denormalized into each event row so
    the log is self-describing during recovery (EB-003/§5.1)."""
    return require_registered(type_name).recovery_grade


def validate_registration(envelope: EventEnvelope) -> None:
    """Publish-time check: the type is registered, its recovery_grade
    matches the registry (no per-publish override of the redo contract),
    and its payload carries the schema's required fields."""
    entry = require_registered(envelope.type)
    if envelope.recovery_grade != entry.recovery_grade:
        raise UnregisteredEventTypeError(
            f"{envelope.type}: recovery_grade={envelope.recovery_grade} "
            f"contradicts the registry ({entry.recovery_grade}) — the redo "
            "contract is the registry's, not the publisher's (EB-003)"
        )
    missing = [f for f in entry.required_payload_fields if f not in envelope.payload]
    if missing:
        raise UnregisteredEventTypeError(
            f"{envelope.type}: payload missing required fields {missing} (§6.3)"
        )
