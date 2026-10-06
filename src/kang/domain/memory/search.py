"""Kang-facing memory search — 06_MEMORY Part X, default and deep modes
(ADR-056).

Layer: domain (stdlib + domain/ports only). The query embedding arrives
through an injected callable (`Router.embed` at the composition root), the
same seam the embedding worker uses.

Constitutional home: 06 §5.2 (the scorer, `retrieval.py`), Part X (default:
hybrid over retrievable records; deep: adds archived and superseded,
"exact recall over semantic vibes"; zero-hit honesty — never padded), 07 Part
XIV (the candidate fetch: vector k=64 + FTS k=64, ADR-056 D1), D010 (the
query text is embedded under `privacy_tier="private"`, so it can only ever
reach a local provider — ADR-056 D6), A9 (no embedding provider → lexical
results with a declared marker, never a failure).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from kang.domain.memory.retrieval import (
    RetrievalCandidate,
    ScoredRecord,
    score_candidates,
)
from kang.domain.ports.embedding_index import EMBEDDABLE_STATUSES, EmbeddingIndex
from kang.domain.ports.memory_config import ScoringConfig
from kang.domain.ports.memory_search import MemorySearchStore
from kang.domain.ports.memory_store import MemoryRecord
from kang.domain.ports.model_provider import (
    EmbeddingResult,
    NoProviderAvailable,
    ProviderUnavailable,
    TaskSpec,
)

__all__ = [
    "CANDIDATE_K",
    "DEEP_STATUSES",
    "MAX_NEAREST_MISSES",
    "SearchDeps",
    "SearchOutcome",
    "SearchRequest",
    "search_memory",
]

# 07 Part XIV's own candidate counts: "vec k=64 + FTS k=64".
CANDIDATE_K = 64
# 06 Part X: deep mode "includes archived + superseded (badged)".
DEEP_STATUSES = (*EMBEDDABLE_STATUSES, "archived", "superseded")
# 06 Part X: zero hits show "nearest-miss suggestions clearly labeled as not
# matches" — a handful, not a page.
MAX_NEAREST_MISSES = 3

# (spec, texts, model) -> EmbeddingResult — `Router.embed`, model-pinned.
EmbedQuery = Callable[[TaskSpec, tuple[str, ...], str], EmbeddingResult]


@dataclass(frozen=True)
class SearchRequest:
    query: str
    mode: str  # "default" | "deep"
    types: tuple[str, ...] | None
    min_tier: int | None
    limit: int
    now: datetime


@dataclass(frozen=True)
class SearchDeps:
    store: MemorySearchStore
    index: EmbeddingIndex
    embed: EmbedQuery
    config: ScoringConfig


@dataclass(frozen=True)
class SearchOutcome:
    matches: tuple[tuple[ScoredRecord, MemoryRecord], ...]
    nearest_misses: tuple[tuple[ScoredRecord, MemoryRecord], ...]
    degraded: str | None  # "semantic_unavailable" when vectors could not serve


def search_memory(deps: SearchDeps, request: SearchRequest) -> SearchOutcome:
    statuses = EMBEDDABLE_STATUSES if request.mode == "default" else DEEP_STATUSES
    distances, degraded = _semantic(deps, request)
    lexical = {
        hit.record_id: hit.bm25
        for hit in deps.store.lexical(
            _lexical_query(request.query, deps.config.stopwords),
            statuses,
            request.types,
            CANDIDATE_K,
        )
    }
    ids = sorted(set(distances) | set(lexical))
    records = {
        r.id: r for r in deps.store.records(ids) if _admissible(r, statuses, request)
    }
    candidates = [
        RetrievalCandidate(
            record_id=r.id,
            type=r.type,
            updated_at=datetime.fromisoformat(r.updated_at),
            importance=r.importance,
            pinned=r.pinned,
            distance=distances.get(r.id),
            bm25=lexical.get(r.id),
        )
        for r in records.values()
    ]
    use_semantic = request.mode == "default" and degraded is None
    scored = score_candidates(candidates, request.now, deps.config, use_semantic)
    matches = tuple((s, records[s.record_id]) for s in scored if s.is_match)
    misses = tuple((s, records[s.record_id]) for s in scored if not s.is_match)
    return SearchOutcome(
        matches=matches[: request.limit],
        nearest_misses=() if matches else misses[:MAX_NEAREST_MISSES],
        degraded=degraded,
    )


def _lexical_query(query: str, stopwords: frozenset[str]) -> str:
    """Kang's words minus the configured stopwords (ADR-056 D4's
    correction). The semantic half keeps the whole question — embedding
    models read function words as meaning."""
    words = re.findall(r"\w+", query, flags=re.UNICODE)
    return " ".join(w for w in words if w.casefold() not in stopwords)


def _semantic(
    deps: SearchDeps, request: SearchRequest
) -> tuple[dict[str, float], str | None]:
    """The vector half. Deep mode is lexical by definition (06 Part X), and
    archived/superseded records hold no vector anyway (ADR-055 D4)."""
    if request.mode != "default":
        return {}, None
    active = [v for v in deps.index.versions_to_fill() if v.status == "active"]
    if not active:
        return {}, "semantic_unavailable"
    version = active[0]
    spec = TaskSpec(
        task_class="embedding",
        privacy_tier="private",  # Kang's own words: local providers only
        context_size=len(request.query) // 4 + 1,
        latency_tolerance="interactive",
    )
    try:
        result = deps.embed(spec, (request.query,), version.model)
    except (NoProviderAvailable, ProviderUnavailable):
        return {}, "semantic_unavailable"
    (vector,) = result.vectors
    if result.model != version.model or len(vector) != version.dim:
        return {}, "semantic_unavailable"
    neighbors = deps.index.nearest_memory(version.ver, vector, CANDIDATE_K)
    return {n.record_id: n.distance for n in neighbors}, None


def _admissible(
    record: MemoryRecord, statuses: tuple[str, ...], request: SearchRequest
) -> bool:
    """06 §5.2's filters-before-scoring, re-checked on the hydrated row: the
    vector half cannot prefilter (vec0 has no metadata columns here)."""
    return (
        record.status in statuses
        and record.sensitivity != "private"
        and (request.types is None or record.type in request.types)
        and (request.min_tier is None or record.trust_tier >= request.min_tier)
    )
