"""Event-type registry (§6.3): closed taxonomy, publish-time admission."""

from __future__ import annotations

import pytest

from kang.kernel.bus.event_registry import (
    EVENT_TYPES,
    EventType,
    UnregisteredEventTypeError,
    is_recovery_grade,
    require_registered,
    validate_registration,
)
from tests.fixtures.event_log_contract import make_envelope


def test_task_types_are_registered_and_recovery_grade():
    for name in ("task.created", "task.updated"):
        assert is_recovery_grade(name)
        assert EVENT_TYPES[name].category == "domain"


def test_unregistered_type_is_rejected():
    with pytest.raises(UnregisteredEventTypeError, match="not registered"):
        require_registered("task.teleported")


def test_valid_task_envelope_passes_registration():
    validate_registration(make_envelope(0))  # recovery-grade, full payload


def test_recovery_grade_mismatch_is_rejected():
    # Registry says task.created is recovery-grade; an envelope claiming
    # otherwise contradicts the redo contract (EB-003).
    envelope = make_envelope(0, recovery_grade=False)
    with pytest.raises(UnregisteredEventTypeError, match="recovery_grade"):
        validate_registration(envelope)


def test_missing_required_payload_field_is_rejected():
    envelope = make_envelope(0, payload={"id": "task-0001"})  # missing the rest
    with pytest.raises(UnregisteredEventTypeError, match="missing required fields"):
        validate_registration(envelope)


def test_category_is_validated_on_construction():
    with pytest.raises(ValueError, match="category"):
        EventType(
            name="x.happened",
            category="nonsense",
            recovery_grade=False,
            plugin_visible=False,
            version_introduced="0.1",
        )


# ---- ADR-029: `task.*` is the TODO domain, and only that -----------------


def test_task_updated_is_a_domain_recovery_grade_todo_mutation():
    """ADR-029 closes a live doc/code contradiction: 15_EVENT_BUS §6.1's
    Lifecycle row used to list `task.updated` "(API long-running tasks)"
    with grade "others no", while ADR-004 had already registered
    `task.updated` as a domain, recovery-grade TODO mutation.

    That is not cosmetic. `validate_registration` refuses any publish
    whose recovery_grade disagrees with the registry ("the redo contract
    is the registry's, not the publisher's" — EB-003), so M7 publishing
    `task.updated` for an agent run, exactly as the Lifecycle row
    instructed, would have been rejected at runtime by a guard working
    as designed.

    This test is the lock: re-specifying `task.updated` as a Lifecycle /
    non-recovery-grade type fails here rather than surfacing as a
    confusing publish rejection mid-way through building M7.
    """
    entry = require_registered("task.updated")
    assert entry.category == "domain"
    assert entry.recovery_grade is True
    assert is_recovery_grade("task.updated") is True


def test_no_async_work_type_squats_on_the_task_namespace():
    """The async-work resource is `invocation` (ADR-029 D1). Nothing in
    the registry may claim `task.*` for execution machinery — the TODO
    domain owns that prefix. `invocation.updated` is deliberately NOT
    registered yet: it has no publisher and no consumer, and registering
    it early is the speculative-structure anti-pattern ADR-026 declined
    for `held_action.*` (ADR-029 Consequences)."""
    task_types = {n: e for n, e in EVENT_TYPES.items() if n.startswith("task.")}
    assert set(task_types) == {"task.created", "task.updated"}
    assert all(e.category == "domain" for e in task_types.values())
    assert "invocation.updated" not in EVENT_TYPES
