"""RealSleeper — wall-time delay for retry backoff.

Layer: kernel/runtime (17 §7: backoff/supervised-task helpers are kernel
machinery; the kernel MAY use what its machinery needs — here, stdlib time).
Constitutional home: 15_EVENT_BUS EB-007.4 (timed exponential backoff
between delivery attempts). Injected behind the Sleeper port so tests use a
fake and never wait (13 §1.4).

Scope note: synchronous `time.sleep` is correct for the current synchronous
core; when an asyncio runtime lands (04_ARCHITECTURE names no decision
number for this — D015 is Observability, not async, a stale citation
corrected here, 2026-08-09), an AsyncSleeper joins behind the same port.
This is not a wall-clock READ (the banned pattern) — it is a bounded
delay, the port's whole purpose.
"""

from __future__ import annotations

import time

__all__ = ["RealSleeper"]


class RealSleeper:
    """Sleeper backed by time.sleep."""

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)
