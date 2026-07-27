"""FakeDeadlineStore — in-memory DeadlineStore, contract-paired (13 §2.3).

Layer: adapters/fakes.
Constitutional home: 11_CODING §5/§7 (every port has an in-memory fake).
A fake that lies is a red build (13 §2.3): the same contract suite runs
against this and SqliteDeadlineStore, so the revision discipline and the
`active()` ordering are mirrored here rather than approximated.
"""

from __future__ import annotations

from dataclasses import replace

from kang.domain.ports.clock import Clock
from kang.domain.ports.deadline_store import (
    Deadline,
    DeadlineNotFoundError,
    DeadlineRevisionConflictError,
)

__all__ = ["FakeDeadlineStore"]


class FakeDeadlineStore:
    """DeadlineStore over a dict, mirroring the revision guards."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._deadlines: dict[str, Deadline] = {}
        self._tombstones: list[tuple[str, str]] = []

    def create(self, deadline: Deadline) -> None:
        if deadline.id in self._deadlines:
            raise ValueError(f"duplicate deadline {deadline.id}")
        self._deadlines[deadline.id] = deadline

    def get(self, deadline_id: str) -> Deadline:
        try:
            return self._deadlines[deadline_id]
        except KeyError:
            raise DeadlineNotFoundError(deadline_id) from None

    def update(self, deadline: Deadline) -> Deadline:
        current = self.get(deadline.id)
        if current.revision != deadline.revision:
            raise DeadlineRevisionConflictError(
                f"deadline {deadline.id}: expected revision "
                f"{deadline.revision}, store has {current.revision}"
            )
        committed = replace(
            deadline, updated_at=self._clock.now(), revision=deadline.revision + 1
        )
        self._deadlines[deadline.id] = committed
        return committed

    def active(self) -> list[Deadline]:
        return sorted(
            (d for d in self._deadlines.values() if d.status == "tracked"),
            key=lambda d: (d.at, d.id),
        )

    def delete(self, deadline_id: str, deleted_by: str) -> None:
        if deadline_id not in self._deadlines:
            raise DeadlineNotFoundError(deadline_id)
        del self._deadlines[deadline_id]
        self._tombstones.append((deadline_id, deleted_by))
