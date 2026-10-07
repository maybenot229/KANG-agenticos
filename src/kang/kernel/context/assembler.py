"""The Context Assembler — kernel infrastructure, not an agent (ADR-058 D1).

Layer: kernel.
Constitutional home: 05_AGENTS §3 phase 3 ("built per the agent's recipe;
logged before the first model call. No agent constructs its own context"),
AG-009 (deterministic, kernel-owned, scope-enforced), 06_MEMORY §5.4, Part
XI, §12.2 (default-deny `memory.read:{view}` grants).

Gathers inputs through ports — standing records, ADR-056's two retrieval
halves and scorer — enforces the recipe's grant before reading anything, and
hands the rest to the pure core (`domain/memory/assembly.py`). P1 is
standing context (rules, then pinned, then profile/preference); P2 is scored
relevance; P0/P3/P4 have no producer yet and are recorded as such.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, replace

from kang.domain.memory.assembly import (
    AssemblyItem,
    ManifestMeta,
    allocate,
    build_manifest,
    estimate_tokens,
    render_context,
    render_line,
    suppression_reason,
)
from kang.domain.memory.search import (
    EmbedQuery,
    SearchDeps,
    SearchRequest,
    search_memory,
)
from kang.domain.ports.clock import Clock
from kang.domain.ports.context_recipe import ContextRecipe, RecipeNotFound
from kang.domain.ports.embedding_index import EMBEDDABLE_STATUSES, EmbeddingIndex
from kang.domain.ports.memory_config import (
    AssemblyConfig,
    ScoringConfig,
    ScoringWeights,
)
from kang.domain.ports.memory_search import MemorySearchStore
from kang.domain.ports.memory_store import MemoryRecord
from kang.kernel.permissions.engine import PermissionEngine

__all__ = ["Assembly", "AssemblerDeps", "AssemblyRequest", "ContextAssembler"]

# P1's internal order (ADR-058 D3): rules are always included first.
_STANDING_ORDER = {"rule": 0, "pinned": 1, "profile": 2, "preference": 2}


@dataclass(frozen=True)
class AssemblerDeps:
    store: MemorySearchStore
    index: EmbeddingIndex
    embed: EmbedQuery
    scoring: ScoringConfig | None  # None: memory.toml [scoring]/[search] unusable
    assembly: AssemblyConfig | None  # None: memory.toml [assembly] unusable
    recipes: dict[str, ContextRecipe]
    permissions: PermissionEngine
    clock: Clock


@dataclass(frozen=True)
class AssemblyRequest:
    agent_id: str
    recipe_id: str
    query: str
    correlation_id: str


@dataclass(frozen=True)
class Assembly:
    context: str  # rendered `[MEM:id]` lines for the prompt
    manifest: str  # canonical, content-free JSON (ADR-058 D5)


class ContextAssembler:
    def __init__(self, deps: AssemblerDeps) -> None:
        self._deps = deps

    def assemble(self, request: AssemblyRequest) -> Assembly:
        recipe = self._deps.recipes.get(request.recipe_id)
        if recipe is None:
            raise RecipeNotFound(
                f"agent {request.agent_id!r} names recipe {request.recipe_id!r}, "
                "which no shipped recipe defines"
            )
        meta = ManifestMeta(
            invocation=request.correlation_id,
            agent=request.agent_id,
            recipe=recipe,
            assembled_at=self._deps.clock.now().isoformat(),
            query_sha256=hashlib.sha256(request.query.encode("utf-8")).hexdigest(),
        )
        refused = self._refusal(request.agent_id, recipe)
        if refused is not None:
            manifest = build_manifest(
                meta, None, {}, "unused", refused, recipe.budget_tokens
            )
            return Assembly(render_context(()), manifest)
        scoring, assembly = self._deps.scoring, self._deps.assembly
        assert scoring is not None and assembly is not None  # _refusal checked
        suppressed: Counter[str] = Counter()
        seen: set[str] = set()  # each record is judged once, counted once
        standing = self._standing(recipe, suppressed, seen)
        relevance, semantic = self._relevance(
            request, _with_overrides(scoring, recipe), seen, suppressed
        )
        allocation = allocate(
            [*standing, *relevance], recipe.budget_tokens, assembly.budget_shares
        )
        manifest = build_manifest(
            meta, allocation, dict(suppressed), semantic, None, recipe.budget_tokens
        )
        return Assembly(render_context(allocation.included), manifest)

    def _refusal(self, agent_id: str, recipe: ContextRecipe) -> str | None:
        """ADR-058 D4: no grant, no read. A missing config is also refused
        (it fails closed and never defaults)."""
        if self._deps.scoring is None or self._deps.assembly is None:
            return "config"
        principal = f"agent:{agent_id}"
        if not self._deps.permissions.allows(principal, f"memory.read:{recipe.view}"):
            return "scope"
        if recipe.clearance == "sensitive" and not self._deps.permissions.allows(
            principal, "memory.read:sensitive"
        ):
            return "scope"
        return None

    def _standing(
        self, recipe: ContextRecipe, suppressed: Counter[str], seen: set[str]
    ) -> list[AssemblyItem]:
        items = []
        for record in self._deps.store.standing(EMBEDDABLE_STATUSES):
            seen.add(record.id)
            reason = suppression_reason(record, recipe)
            if reason is not None:
                suppressed[reason] += 1
                continue
            items.append(_item(record, "p1", _why_standing(record), None))
        items.sort(key=lambda i: (_STANDING_ORDER[i.why], i.record.id))
        return items

    def _relevance(
        self,
        request: AssemblyRequest,
        config: ScoringConfig,
        seen: set[str],
        suppressed: Counter[str],
    ) -> tuple[list[AssemblyItem], str]:
        recipe = self._deps.recipes[request.recipe_id]
        if not request.query.strip():
            return [], "unused"
        outcome = search_memory(
            SearchDeps(self._deps.store, self._deps.index, self._deps.embed, config),
            SearchRequest(
                query=request.query,
                mode="default",
                types=recipe.types,
                min_tier=recipe.tier_floor,
                limit=recipe.k * 4,
                now=self._deps.clock.now(),
            ),
        )
        items = []
        for scored, record in outcome.matches:
            if record.id in seen:  # already judged as standing context
                continue
            reason = suppression_reason(record, recipe)
            if reason is not None:
                suppressed[reason] += 1
                continue
            items.append(_item(record, "p2", "relevance", scored))
        semantic = "unavailable" if outcome.degraded else "ok"
        return items[: recipe.k], semantic


def _item(record: MemoryRecord, klass: str, why: str, scored) -> AssemblyItem:
    line = render_line(record)
    return AssemblyItem(record, klass, why, scored, line, estimate_tokens(line))


def _why_standing(record: MemoryRecord) -> str:
    if record.type == "rule":
        return "rule"
    if record.pinned:
        return "pinned"
    return record.type  # profile | preference


def _with_overrides(scoring: ScoringConfig, recipe: ContextRecipe) -> ScoringConfig:
    if not recipe.weights:
        return scoring
    weights = vars(scoring.weights) | recipe.weights
    return replace(scoring, weights=ScoringWeights(**weights))
