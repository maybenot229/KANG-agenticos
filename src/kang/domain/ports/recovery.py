"""Recovery-application port — re-apply recovery-grade events to state.

Layer: domain/ports. Ports own their datatypes (17 §7).
Constitutional home: 15_EVENT_BUS EB-003 (re-application MUST be idempotent,
keyed by entity id + revision), §4 (the reconciliation pass re-applies
recovery-grade events and checks entity existence for the orphan verdict).
The re-application SQL lives in adapters/sqlite (DB-002); this is the
interface the caged reconciliation module (kernel/bus) depends on — so
reconciliation stays adapter-free (17 §4.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

__all__ = ["ReapplyOutcome", "RecoveryApplier", "RecoveryError"]


class RecoveryError(Exception):
    """The event cannot be re-applied. Loud, never half-applied (07 F3)."""


@dataclass(frozen=True)
class ReapplyOutcome:
    """What re-application did: 'applied' | 'noop' (already committed)."""

    event_id: str
    outcome: str


class RecoveryApplier(Protocol):
    """Re-applies recovery-grade truth and answers existence questions —
    the two things the §4 reconciliation pass asks of state."""

    def reapply(self, envelope) -> ReapplyOutcome:
        """Idempotently re-apply a recovery-grade event's self-sufficient
        payload (EB-003). Raises RecoveryError if it cannot."""
        ...

    def entity_exists(self, kind: str, entity_id: str) -> bool:
        """Whether the referenced entity is present in state — the orphan
        decision for a non-recovery-grade pending event (§4.3)."""
        ...
