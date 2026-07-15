"""Sleeper port — injected delay, so retry backoff is testable (13 §1.4).

Layer: domain/ports.
Constitutional home: 11_CODING §14 (time is injected — the same discipline
as the clock; a real sleep is wall-time and must sit behind a port so tests
never actually wait), 15_EVENT_BUS EB-007.4 (exponential backoff between
delivery attempts). The real sleeper lives in kernel/runtime (17 §7:
"backoff → kernel/runtime"); the fake records requested delays.
"""

from __future__ import annotations

from typing import Protocol

__all__ = ["Sleeper"]


class Sleeper(Protocol):
    """Pauses the caller for `seconds`. Real: wall-time. Fake: records."""

    def sleep(self, seconds: float) -> None: ...
