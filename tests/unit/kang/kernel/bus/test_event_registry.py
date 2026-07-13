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
