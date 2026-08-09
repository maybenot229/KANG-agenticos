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
    "namespace_of",
    "require_registered",
    "validate_registration",
]

# The core namespace: core event types are unprefixed (EB-005 §5.1). Plugin
# types are `plugin.{id}.*` and belong to namespace `plugin.{id}`.
CORE_NAMESPACE = "kang"

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

# Same contract for the deadline entity (ADR-004): the full field set, so a
# lost `tracked → alerted` write replays exactly. Mirrors 07 §5.2's columns
# and `deadline_service.deadline_event_payload()`, which builds it.
_DEADLINE_PAYLOAD_FIELDS = (
    "id",
    "competition_id",
    "project_id",
    "kind",
    "title",
    "at",
    "lead_days",
    "status",
    "created_at",
    "updated_at",
    "device_id",
    "revision",
)

# Same contract for the project entity (ADR-013): the full field set, so a
# lost project.created write replays exactly. Mirrors 07 §5.2's columns and
# `project_service.project_event_payload()`, which builds it.
_PROJECT_PAYLOAD_FIELDS = (
    "id",
    "name",
    "description",
    "status",
    "vault_folder",
    "github_repo",
    "goal_id",
    "created_at",
    "updated_at",
    "device_id",
    "revision",
)

# Same contract for the competition entity (ADR-014): the full field set,
# so a lost competition.created write replays exactly. Mirrors 07 §5.2's
# columns and `competition_service.competition_event_payload()`, which
# builds it. `evaluation`/`result` are always None from this handler
# (Phase 3's own write path), but present in the shape for when that
# consumer arrives.
_COMPETITION_PAYLOAD_FIELDS = (
    "id",
    "name",
    "url",
    "status",
    "evaluation",
    "result",
    "project_id",
    "created_at",
    "updated_at",
    "device_id",
    "revision",
)

# Same contract for the milestone entity (ADR-015): the full field set, so
# a lost milestone.created write replays exactly. Mirrors 07 §5.2's
# columns and `milestone_service.milestone_event_payload()`, which builds
# it.
_MILESTONE_PAYLOAD_FIELDS = (
    "id",
    "project_id",
    "title",
    "due",
    "status",
    "created_at",
    "updated_at",
    "device_id",
    "revision",
)

# Same contract for the goal entity (ADR-016, the standing pattern
# ADR-013/014/015 established, generalized): the full field set, so a
# lost goal.created write replays exactly. Mirrors 07 §5.2's columns and
# `goal_service.goal_event_payload()`, which builds it.
_GOAL_PAYLOAD_FIELDS = (
    "id",
    "title",
    "description",
    "horizon",
    "status",
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
    # ---- M5, per ADR-004 -------------------------------------------------
    # Deadline TRUTH MUTATIONS: recovery-grade, because EB-003 requires it
    # for "task/deadline/competition truth mutations" and losing a deadline
    # row is the one failure the "never misses a deadline" promise forbids.
    EventType(
        name="deadline.created",
        category="domain",
        recovery_grade=True,
        plugin_visible=True,
        version_introduced="0.1",
        required_payload_fields=_DEADLINE_PAYLOAD_FIELDS,
    ),
    EventType(
        name="deadline.updated",
        category="domain",
        recovery_grade=True,
        plugin_visible=True,
        version_introduced="0.1",
        required_payload_fields=_DEADLINE_PAYLOAD_FIELDS,
    ),
    # The approaching FACT: not recovery-grade. EB-008 rule 2 states it
    # literally — "deadline.approaching changes no row." Its consumers are
    # the notifier and the planner (05 Appendix F): a trigger, not a redo
    # record. The status mutation it accompanies rides deadline.updated.
    EventType(
        name="deadline.approaching",
        category="domain",
        recovery_grade=False,
        plugin_visible=True,
        version_introduced="0.1",
        required_payload_fields=("deadline_id", "title", "at"),
    ),
    # An accelerant over the durable queue row (15 §6.2), never the work
    # item itself — so a lost event costs latency, never a notification.
    # Not plugin-visible: draining the queue is core notifier machinery;
    # plugins reach Kang through their granted notify scope, not by
    # subscribing to the notifier's own input.
    EventType(
        name="notification.requested",
        category="notification",
        recovery_grade=False,
        plugin_visible=False,
        version_introduced="0.1",
        required_payload_fields=("notification_id", "priority"),
    ),
    # The plan is DERIVED state (02_PRD's dependency map) and deterministic
    # (same inputs ⇒ identical plan), therefore rebuildable, therefore not
    # recovery-grade — 07 §1.4 reserves authority for non-derivable truth.
    # Its durable effect (plan_date on N tasks) rides task.updated.
    EventType(
        name="plan.generated",
        category="domain",
        recovery_grade=False,
        plugin_visible=True,
        version_introduced="0.1",
        required_payload_fields=("plan_date",),
    ),
    # ---- project.created, per ADR-013 ------------------------------------
    # A project row is Tier-1 truth — referenced by task/competition/
    # deadline FKs already live in the schema — by the same argument
    # ADR-004 made for deadline.created: losing one on crash recovery would
    # silently corrupt the read-shape of everything that points at it.
    EventType(
        name="project.created",
        category="domain",
        recovery_grade=True,
        plugin_visible=True,
        version_introduced="0.1",
        required_payload_fields=_PROJECT_PAYLOAD_FIELDS,
    ),
    # ---- competition.created, per ADR-014 --------------------------------
    # EB-003 names "competition truth mutations" as REQUIRED recovery-grade
    # directly (unlike project, which ADR-013 had to argue by analogy).
    # competition.updated is deliberately NOT registered: no status-
    # transition or evaluation-write operation exists yet (Phase 3
    # territory) — same non-speculation discipline as project.updated.
    EventType(
        name="competition.created",
        category="domain",
        recovery_grade=True,
        plugin_visible=True,
        version_introduced="0.1",
        required_payload_fields=_COMPETITION_PAYLOAD_FIELDS,
    ),
    # ---- milestone.created, per ADR-015 ----------------------------------
    # A milestone row is real, addressable project state; losing one on
    # crash recovery silently corrupts that project's own milestone list —
    # same argument ADR-013 made for project.created.
    EventType(
        name="milestone.created",
        category="domain",
        recovery_grade=True,
        plugin_visible=True,
        version_introduced="0.1",
        required_payload_fields=_MILESTONE_PAYLOAD_FIELDS,
    ),
    # ---- goal.created, per ADR-016 (the standing pattern, first applied
    # here) -------------------------------------------------------------
    # A goal row is real, addressable state — project.goal_id can
    # reference it, and 07 §5.2 already commits to this table holding
    # Kang's real quarter/year goals from M5's first runtime population.
    EventType(
        name="goal.created",
        category="domain",
        recovery_grade=True,
        plugin_visible=True,
        version_introduced="0.1",
        required_payload_fields=_GOAL_PAYLOAD_FIELDS,
    ),
    # ---- milestone.updated / goal.updated / project.updated, per ADR-018
    # (the standing .updated pattern, generalizing ADR-016's own precedent
    # to transitions) ------------------------------------------------------
    # milestone.updated carries reach/miss/drop; goal.updated carries
    # achieve/revise/retire; project.updated carries complete only (see
    # ADR-018's own scope ruling on why project's remaining transitions
    # — pause/resume/archive/abandon — stay unbuilt). Same full-row,
    # recovery-grade shape as each entity's own .created type — losing a
    # transition on crash recovery would silently revert the row.
    EventType(
        name="milestone.updated",
        category="domain",
        recovery_grade=True,
        plugin_visible=True,
        version_introduced="0.1",
        required_payload_fields=_MILESTONE_PAYLOAD_FIELDS,
    ),
    EventType(
        name="goal.updated",
        category="domain",
        recovery_grade=True,
        plugin_visible=True,
        version_introduced="0.1",
        required_payload_fields=_GOAL_PAYLOAD_FIELDS,
    ),
    EventType(
        name="project.updated",
        category="domain",
        recovery_grade=True,
        plugin_visible=True,
        version_introduced="0.1",
        required_payload_fields=_PROJECT_PAYLOAD_FIELDS,
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


def namespace_of(type_name: str) -> str:
    """The publish namespace a type belongs to (EB-005 §5.1 / EB-010): core
    types → `kang`; `plugin.{id}.*` → `plugin.{id}`. This is the qualifier
    of the `events.publish:{namespace}` capability the publisher must hold."""
    if type_name.startswith("plugin."):
        parts = type_name.split(".")
        if len(parts) < 3:
            raise UnregisteredEventTypeError(
                f"plugin event type {type_name!r} must be plugin.{{id}}.{{name}}"
            )
        return f"plugin.{parts[1]}"
    return CORE_NAMESPACE


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
