"""SystemClock — the real wall clock (the one place datetime.now lives).

Layer: adapters/os_windows (OS-services adapter; the banned-pattern lint
sanctions wall-clock reads only here — everywhere else time is the injected
Clock port, 11 §14).
Constitutional home: 11_CODING §14 (the clock is injected; datetime.now
outside the clock adapter is lint-banned). Returns aware UTC, as the Clock
port requires.
"""

from __future__ import annotations

from datetime import datetime, timezone

__all__ = ["SystemClock"]


class SystemClock:
    """Clock backed by the operating system's UTC time."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)
