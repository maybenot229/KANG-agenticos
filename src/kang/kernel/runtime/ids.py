"""UUIDv7 generation — time-ordered ids (07_DATABASE "Why UUIDv7").

Layer: kernel/runtime (machinery).
Constitutional home: 07_DATABASE §5 (UUIDv7: time-ordered index-friendly
inserts, collision-free across devices; adopt at v0.1). stdlib has no
uuid7 in 3.12, so it is assembled here per RFC 9562. The timestamp comes
from the injected clock and the randomness from an injected `rand` (default
os.urandom) — so tests can make ids deterministic (11 §14 injection).
"""

from __future__ import annotations

import os
from typing import Callable

__all__ = ["uuid7"]


def uuid7(timestamp_ms: int, rand: Callable[[int], bytes] = os.urandom) -> str:
    """A UUIDv7 string for the given Unix-millis timestamp (RFC 9562):
    48-bit ms | version 7 | 12-bit rand_a | variant 0b10 | 62-bit rand_b."""
    ts = timestamp_ms & ((1 << 48) - 1)
    rand_a = int.from_bytes(rand(2), "big") & 0x0FFF
    rand_b = int.from_bytes(rand(8), "big") & ((1 << 62) - 1)
    value = ts << 80
    value |= 0x7 << 76
    value |= rand_a << 64
    value |= 0b10 << 62
    value |= rand_b
    hexed = f"{value:032x}"
    return f"{hexed[0:8]}-{hexed[8:12]}-{hexed[12:16]}-{hexed[16:20]}-{hexed[20:32]}"
