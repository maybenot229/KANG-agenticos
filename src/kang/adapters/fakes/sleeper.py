"""FakeSleeper — records requested delays without waiting (13 §1.4).

Layer: adapters/fakes.
Constitutional home: 11_CODING §5/§7 (every port has an in-memory fake).
The recorded `delays` are how a test proves backoff timing was requested —
"redelivery waits the configured backoff" without any real wall-time pass.
"""

from __future__ import annotations

__all__ = ["FakeSleeper"]


class FakeSleeper:
    """Sleeper that never sleeps; it records each requested duration."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.delays.append(seconds)
