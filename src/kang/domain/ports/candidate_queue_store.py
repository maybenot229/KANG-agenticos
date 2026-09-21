"""CandidateQueueStore port — `memory_candidate_queue`, the quarantine
(ADR-051 D10; ADR-048 D1; 06_MEMORY §4.3).

Layer: domain/ports.
A candidate lives ONLY here until Kang approves it; the queue row's id is the
id the `memory_record` row receives on approval (ADR-048 D1). No sync quartet,
no change capture: operational, never synchronized (ADR-005's shape).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

__all__ = ["CANDIDATE_RESOLUTIONS", "Candidate", "CandidateQueueStore"]

# 07 §5.1's CHECK on `memory_candidate_queue.resolved`.
CANDIDATE_RESOLUTIONS = ("approved", "edited", "rejected", "expired")


@dataclass(frozen=True)
class Candidate:
    """One queue row. `payload` is the full proposed record as JSON-shaped
    data (07 §5.1), including the proposer's principal and device."""

    id: str
    payload: dict[str, Any]
    proposed_at: str
    expires_at: str
    flags: tuple[str, ...] = ()
    flag_context: str | None = None
    resolved: str | None = None
    resolved_at: str | None = None

    @property
    def pending(self) -> bool:
        return self.resolved is None


class CandidateQueueStore(Protocol):
    """Persistence port for the approval queue."""

    def enqueue(self, candidate: Candidate) -> None: ...

    def get(self, candidate_id: str) -> Candidate | None: ...

    def list_queue(self, limit: int) -> tuple[Candidate, ...]:
        """Pending candidates first, oldest first (ties: higher confidence
        first — confidence orders the queue and nothing else, M-003), then
        resolved ones, oldest first."""
        ...

    def resolve(self, candidate_id: str, resolution: str, at: str) -> bool:
        """Set `resolved`/`resolved_at` on a *pending* row. Returns False
        (and changes nothing) if the row is absent or already resolved.
        Joins an already-open transaction if the caller holds one."""
        ...

    def expire_due(self, now: str) -> tuple[str, ...]:
        """Resolve as `expired` every pending row whose `expires_at < now`
        (06 §4.3: silence is a veto). Returns the ids; idempotent."""
        ...
