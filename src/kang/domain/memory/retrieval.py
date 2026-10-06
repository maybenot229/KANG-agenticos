"""The hybrid relevance scorer — 06_MEMORY §5.2, as a pure function
(ADR-056 D2).

Layer: domain (stdlib + domain/ports only). No I/O, no clock: `now` is a
parameter (11 §14), so the same candidates and the same `now` always give the
same ranking, to the decimal (13 §2.6).

    score(m) = w_s·sim + w_x·bm25_n + w_r·e^(−λΔt) + w_i·imp + w_c·ctx

Each term, as built (ADR-056 D2):
- `sim` — cosine similarity, `1 − cosine distance`, clamped to [0, 1]. A
  record with no vector in the queried version scores 0 here (FTS carries it).
- `bm25_n` — FTS5 `bm25()` min-max normalized over this query's lexical
  candidates; the best is 1. FTS5 reports better matches as MORE negative.
  A record with no lexical hit scores 0.
- recency — `e^(−ln 2 · Δt / half_life)`, Δt in days since `updated_at`;
  half-life 0 means no decay (06: "principles don't age").
- `imp` — 1.0 when pinned (06: "pin ⇒ 1.0"), else the record's `importance`.
  The access-frequency component is not built (it needs a write on the read
  path); named in ADR-056 D9.
- `ctx` — 0: the link layer does not exist yet (ADR-056 D9). Kang-facing
  default search weights it 0 anyway (06 Part X).

A candidate is a *match* if it has a lexical hit or `sim` reaches
`match_min_similarity` (ADR-056 D4) — everything else is at most a nearest
miss, never padded into the results (06 Part X).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from kang.domain.ports.memory_config import ScoringConfig

__all__ = ["RetrievalCandidate", "ScoreTerms", "ScoredRecord", "score_candidates"]


@dataclass(frozen=True)
class RetrievalCandidate:
    record_id: str
    type: str
    updated_at: datetime
    importance: float
    pinned: bool
    distance: float | None  # cosine distance from the query; None = no vector hit
    bm25: float | None  # FTS5 bm25(); None = no lexical hit


@dataclass(frozen=True)
class ScoreTerms:
    """Each term before weighting, so "why was this included?" is answerable
    to the decimal (06 §5.2)."""

    semantic: float
    lexical: float
    recency: float
    importance: float
    context: float


@dataclass(frozen=True)
class ScoredRecord:
    record_id: str
    score: float
    terms: ScoreTerms
    is_match: bool


def score_candidates(
    candidates: Sequence[RetrievalCandidate],
    now: datetime,
    config: ScoringConfig,
    use_semantic: bool = True,
) -> tuple[ScoredRecord, ...]:
    """Score and rank, best first; ties broken by record id. With
    `use_semantic=False` (deep mode, or the semantic half unavailable) the
    semantic term is computed for transparency but weighted 0, and only a
    lexical hit is a match."""
    lexical = _normalized_bm25(candidates)
    w = config.weights
    semantic_weight = w.semantic if use_semantic else 0.0
    scored = []
    for c in candidates:
        terms = ScoreTerms(
            semantic=_similarity(c.distance),
            lexical=lexical.get(c.record_id, 0.0),
            recency=_recency(c, now, config.half_life_days),
            importance=1.0 if c.pinned else c.importance,
            context=0.0,
        )
        score = (
            semantic_weight * terms.semantic
            + w.lexical * terms.lexical
            + w.recency * terms.recency
            + w.importance * terms.importance
            + w.context * terms.context
        )
        is_match = c.bm25 is not None or (
            use_semantic
            and c.distance is not None
            and terms.semantic >= config.match_min_similarity
        )
        scored.append(ScoredRecord(c.record_id, score, terms, is_match))
    scored.sort(key=lambda s: s.record_id)
    scored.sort(key=lambda s: s.score, reverse=True)
    return tuple(scored)


def _similarity(distance: float | None) -> float:
    if distance is None:
        return 0.0
    return min(1.0, max(0.0, 1.0 - distance))


def _normalized_bm25(candidates: Sequence[RetrievalCandidate]) -> dict[str, float]:
    goodness = {c.record_id: -c.bm25 for c in candidates if c.bm25 is not None}
    if not goodness:
        return {}
    low, high = min(goodness.values()), max(goodness.values())
    if high == low:
        return {record_id: 1.0 for record_id in goodness}
    return {
        record_id: (value - low) / (high - low) for record_id, value in goodness.items()
    }


def _recency(
    c: RetrievalCandidate, now: datetime, half_life_days: dict[str, float]
) -> float:
    half_life = half_life_days[c.type]
    if half_life <= 0:
        return 1.0
    age_days = max(0.0, (now - c.updated_at).total_seconds() / 86400)
    return math.exp(-math.log(2) * age_days / half_life)
