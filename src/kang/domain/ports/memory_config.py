"""MemoryConfig — the parsed `memory.toml` (ADR-051 D8).

Layer: domain/ports (a datatype, like `ProvidersConfig`). Exactly one real
key today: the candidate expiry window (06 Appendix A `[gate]`).
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["MemoryConfig"]


@dataclass(frozen=True)
class MemoryConfig:
    candidate_expiry_days: int
