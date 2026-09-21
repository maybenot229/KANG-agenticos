"""UnitOfWork port — run several store writes in one transaction
(ADR-051 D3: `memory.approve` inserts the record and resolves the queue row
atomically, inside the bus's `commit_state`, EB-004).

Layer: domain/ports. The stores' write methods join a transaction the unit of
work has opened; they open their own when called alone.
"""

from __future__ import annotations

from typing import Callable, Protocol

__all__ = ["UnitOfWork"]


class UnitOfWork(Protocol):
    def run(self, work: Callable[[], None]) -> None:
        """Execute `work` in one atomic transaction: commit if it returns,
        roll everything back if it raises (and re-raise)."""
        ...
