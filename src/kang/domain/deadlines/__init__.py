"""Deadlines domain area — the deadline entity's invariants and lifecycle.

Layer: domain/deadlines (capability service; deterministic, zero I/O).
Constitutional home: 02_PRD FR-030/FR-031 (track deadlines; alert on
approach with configurable lead times), 07_DATABASE §5.2, 17 §6.1
(algorithms live in domain services, never agents — the deadline_sweep
agent calls this, it does not reimplement it).
"""

from kang.domain.deadlines.deadline_service import (
    DeadlineDraft,
    DeadlineValidationError,
    create_deadline,
    deadline_event_payload,
    due_lead_thresholds,
    mark_alerted,
    mark_met,
    mark_missed,
)

__all__ = [
    "DeadlineDraft",
    "DeadlineValidationError",
    "create_deadline",
    "deadline_event_payload",
    "due_lead_thresholds",
    "mark_alerted",
    "mark_met",
    "mark_missed",
]
