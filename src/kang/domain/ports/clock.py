"""Clock port — all time is injected; wall-clock reads live behind this line.

Layer: domain/ports.
Constitutional home: 11_CODING_STANDARDS §14 (injected clock; datetime.now()
outside the clock adapter is lint-banned).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

__all__ = ["Clock"]


class Clock(Protocol):
    """Source of the current moment. Implementations MUST return aware UTC."""

    def now(self) -> datetime:
        """Return the current instant as an aware UTC datetime."""
        ...
