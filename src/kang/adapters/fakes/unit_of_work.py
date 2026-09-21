"""FakeUnitOfWork — atomic multi-store writes over the in-memory fakes
(13 §2.3). Layer: adapters/fakes. Snapshots each participant before the work
and restores them all if it raises, mirroring SqliteUnitOfWork's rollback."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

__all__ = ["FakeUnitOfWork"]


class FakeUnitOfWork:
    def __init__(self, *participants: Any) -> None:
        self._participants = participants

    def run(self, work: Callable[[], None]) -> None:
        saved = [(p, p.snapshot()) for p in self._participants]
        try:
            work()
        except BaseException:
            for participant, state in saved:
                participant.restore(state)
            raise
