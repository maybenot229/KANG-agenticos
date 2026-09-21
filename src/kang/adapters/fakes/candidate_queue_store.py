"""FakeCandidateQueueStore — in-memory CandidateQueueStore, contract-paired
(13 §2.3). Layer: adapters/fakes. Mirrors the SQLite ordering, the
pending-only `resolve`, and the strict `expires_at < now` sweep."""

from __future__ import annotations

from dataclasses import replace

from kang.domain.ports.candidate_queue_store import CANDIDATE_RESOLUTIONS, Candidate

__all__ = ["FakeCandidateQueueStore"]


def _confidence(candidate: Candidate) -> float:
    return float(candidate.payload.get("confidence", 0.0))


class FakeCandidateQueueStore:
    def __init__(self) -> None:
        self._rows: dict[str, Candidate] = {}

    def enqueue(self, candidate: Candidate) -> None:
        if candidate.id in self._rows:
            raise ValueError(f"duplicate candidate {candidate.id}")
        self._rows[candidate.id] = candidate

    def get(self, candidate_id: str) -> Candidate | None:
        return self._rows.get(candidate_id)

    def list_queue(self, limit: int) -> tuple[Candidate, ...]:
        ordered = sorted(
            self._rows.values(),
            key=lambda c: (
                c.resolved is not None,
                c.proposed_at,
                -_confidence(c),
                c.id,
            ),
        )
        return tuple(ordered[:limit])

    def resolve(self, candidate_id: str, resolution: str, at: str) -> bool:
        if resolution not in CANDIDATE_RESOLUTIONS:
            raise ValueError(f"resolution must be one of {CANDIDATE_RESOLUTIONS}")
        row = self._rows.get(candidate_id)
        if row is None or row.resolved is not None:
            return False
        self._rows[candidate_id] = replace(row, resolved=resolution, resolved_at=at)
        return True

    def expire_due(self, now: str) -> tuple[str, ...]:
        due = sorted(
            (
                c
                for c in self._rows.values()
                if c.resolved is None and c.expires_at < now
            ),
            key=lambda c: (c.expires_at, c.id),
        )
        for candidate in due:
            self._rows[candidate.id] = replace(
                candidate, resolved="expired", resolved_at=now
            )
        return tuple(c.id for c in due)

    # Test/UoW support (not part of the port).
    def snapshot(self) -> dict[str, Candidate]:
        return dict(self._rows)

    def restore(self, state: dict[str, Candidate]) -> None:
        self._rows = dict(state)
