"""ContextRecipe — one agent's versioned context recipe (ADR-058 D2).

Layer: domain/ports (a datatype, like `AgentDefinition`; the loader that
parses recipe files lives in `adapters/config/`).
Constitutional home: 06_MEMORY Part XI ("Recipes are config, versioned, and
logged in manifests"), 05_AGENTS AG-009 (the filter order a recipe
parameterises), §12.2 (the `memory.read:{view}` grant a recipe's view needs).
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["CLEARANCES", "ContextRecipe", "RecipeNotFound"]

# 06 §12.1: `private` is never a clearance — it is excluded from all
# retrieval except a private-tier TaskSpec, which no recipe here builds.
CLEARANCES = ("normal", "sensitive")


class RecipeNotFound(Exception):
    """An agent names a recipe no shipped file defines."""


@dataclass(frozen=True)
class ContextRecipe:
    id: str
    version: int
    view: str  # the scope is `memory.read:{view}`
    types: tuple[str, ...]  # memory types this recipe may see
    clearance: str  # one of CLEARANCES
    tier_floor: int
    confidence_floor: float
    budget_tokens: int
    k: int  # P2 candidates kept before budgeting
    # 06 §5.2 weight overrides (semantic/lexical/recency/importance/context).
    weights: dict[str, float] = field(default_factory=dict)
