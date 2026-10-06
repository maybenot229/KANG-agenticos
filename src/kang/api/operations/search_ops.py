"""memory.search — Kang-facing memory search (ADR-056; 06_MEMORY Part X).

Layer: api. The handler validates the request, runs the domain search
(`domain/memory/search.py`), audits what 06 §12.3 requires, and shapes the
response. No ranking policy lives here.

Audited: every search whose returned records include a `sensitive` one
(06 §12.3: "every sensitive/private access (principal + invocation)") — ids
only, never content. Not audited: routine reads of `normal` records (06
§12.3: "volume would drown the log's usefulness"). `private` records are
never searchable at all (ciphertext only; 06 §12.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kang.api.dispatch import Handler, HandlerContext
from kang.api.errors import ApiError
from kang.api.schemas.memory import DEFAULT_LIMIT, MAX_LIMIT
from kang.domain.memory.retrieval import ScoredRecord
from kang.domain.memory.search import (
    EmbedQuery,
    SearchDeps,
    SearchRequest,
    search_memory,
)
from kang.domain.ports.clock import Clock
from kang.domain.ports.embedding_index import EmbeddingIndex
from kang.domain.ports.memory_config import ScoringConfig
from kang.domain.ports.memory_search import MemorySearchStore
from kang.domain.ports.memory_store import MEMORY_TYPES, MemoryRecord
from kang.kernel.audit.service import AuditService

__all__ = ["MemorySearchDeps", "make_memory_search_handler"]

_MODES = ("default", "deep")


@dataclass(frozen=True)
class MemorySearchDeps:
    store: MemorySearchStore
    index: EmbeddingIndex
    embed: EmbedQuery  # Router.embed, model-pinned (ADR-056 D6)
    audit: AuditService
    clock: Clock
    config: ScoringConfig | None  # None: memory.toml [scoring] absent/invalid


def _request(params: dict[str, Any], now) -> SearchRequest:
    query = params.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ApiError("invalid_request", "memory.search needs a non-empty query")
    mode = params.get("mode") or "default"
    if mode not in _MODES:
        raise ApiError(
            "invalid_request",
            f"mode must be one of {_MODES}; structured mode is not built (ADR-056 D5)",
        )
    types = params.get("types")
    if types is not None and not set(types) <= set(MEMORY_TYPES):
        raise ApiError("invalid_request", f"types must be drawn from {MEMORY_TYPES}")
    min_tier = params.get("min_tier")
    if min_tier is not None and min_tier not in (0, 1, 2):
        raise ApiError("invalid_request", "min_tier must be 0, 1 or 2")
    requested = params.get("limit")
    limit = DEFAULT_LIMIT if requested is None else max(1, min(requested, MAX_LIMIT))
    return SearchRequest(
        query=query,
        mode=mode,
        types=tuple(types) if types is not None else None,
        min_tier=min_tier,
        limit=limit,
        now=now,
    )


def _hit(scored: ScoredRecord, record: MemoryRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "type": record.type,
        "status": record.status,
        "content": record.content,
        "trust_tier": record.trust_tier,
        "sensitivity": record.sensitivity,
        "source_kind": record.source_kind,
        "source_detail": record.source_detail,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "pinned": record.pinned,
        "score": scored.score,
        "terms": dict(vars(scored.terms)),
    }


def make_memory_search_handler(deps: MemorySearchDeps) -> Handler:
    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        request = _request(params, deps.clock.now())
        if deps.config is None:
            raise ApiError(
                "internal",
                "memory.search is unavailable: memory.toml has no valid "
                "[scoring]/[search] (it fails closed and never defaults; "
                "ADR-056 D3 — copy them from config/defaults/memory.toml)",
            )
        outcome = search_memory(
            SearchDeps(deps.store, deps.index, deps.embed, deps.config), request
        )
        shown = [*outcome.matches, *outcome.nearest_misses]
        sensitive = [r.id for _, r in shown if r.sensitivity == "sensitive"]
        if sensitive:
            deps.audit.record(
                context.principal,
                "memory.read.sensitive",
                {"ids": sensitive, "operation": "memory.search"},
                correlation_id=context.correlation_id,
            )
        return {
            "mode": request.mode,
            "results": [_hit(s, r) for s, r in outcome.matches],
            "nearest_misses": [_hit(s, r) for s, r in outcome.nearest_misses],
            "degraded": outcome.degraded,
        }

    return handler
