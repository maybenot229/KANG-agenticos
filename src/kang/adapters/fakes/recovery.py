"""FakeRecoveryApplier — in-memory RecoveryApplier for reconciliation tests.

Layer: adapters/fakes.
Constitutional home: 11_CODING §5/§7 (every port has an in-memory fake);
13 §2.3. Models EB-003 idempotency by entity id + revision without SQL, so
the caged reconciliation module (kernel/bus) can be unit-tested against a
fake exactly as it runs against SqliteRecoveryApplier.
"""

from __future__ import annotations

from kang.domain.ports.eventlog import EventEnvelope
from kang.domain.ports.recovery import ReapplyOutcome, RecoveryError

__all__ = ["FakeRecoveryApplier"]


class FakeRecoveryApplier:
    """Applies task payloads into a dict keyed by id, tracking revision."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def reapply(self, envelope: EventEnvelope) -> ReapplyOutcome:
        if not envelope.recovery_grade:
            raise RecoveryError(f"{envelope.type} is not recovery-grade")
        payload = envelope.payload
        entity_id, revision = payload["id"], payload["revision"]
        current = self.rows.get(entity_id)
        if current is not None and current["revision"] >= revision:
            return ReapplyOutcome(event_id=envelope.event_id, outcome="noop")
        self.rows[entity_id] = dict(payload)
        return ReapplyOutcome(event_id=envelope.event_id, outcome="applied")

    def entity_exists(self, kind: str, entity_id: str) -> bool:
        if kind != "task":
            raise RecoveryError(f"no existence check for kind {kind!r}")
        return entity_id in self.rows
