"""MemoryConfig — the parsed `memory.toml` (ADR-051 D8; ADR-056 D3).

Layer: domain/ports (a datatype, like `ProvidersConfig`). Two independently
parsed parts, each failing closed only for its own reader: `[gate]` (the
candidate expiry window, read by the write gate) and `[scoring]`/`[search]`
(06 §5.2's weights and half-lives, read by `memory.search`). A missing
`[scoring]` refuses search; it never takes the gate down with it.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "ASSEMBLY_CLASSES",
    "AssemblyConfig",
    "MemoryConfig",
    "ScoringConfig",
    "ScoringWeights",
]

# 06 Part XI's five priority classes, highest first.
ASSEMBLY_CLASSES = ("p0", "p1", "p2", "p3", "p4")


@dataclass(frozen=True)
class MemoryConfig:
    candidate_expiry_days: int


@dataclass(frozen=True)
class ScoringWeights:
    """06 §5.2's five weights, in the formula's order."""

    semantic: float
    lexical: float
    recency: float
    importance: float
    context: float


@dataclass(frozen=True)
class ScoringConfig:
    """06 §5.2 + Appendix A `[scoring]`, and ADR-056 D4's `[search]`.
    `half_life_days` names every type in the closed taxonomy (06 M-001);
    0 means no decay."""

    weights: ScoringWeights
    half_life_days: dict[str, float]
    match_min_similarity: float
    # ADR-056 D4's correction (2026-10-06): words dropped from the LEXICAL
    # half of a search. Kang's words are OR-ed, so without this a record
    # sharing only "the" with the query is a lexical hit — padding.
    stopwords: frozenset[str] = frozenset()


@dataclass(frozen=True)
class AssemblyConfig:
    """06 Appendix A `[assembly]` (ADR-058 D3): each priority class's share
    of an assembly's token budget, summing to 1."""

    budget_shares: dict[str, float]
