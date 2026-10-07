"""Context recipe loader — `src/kang/agents/assembly/*.toml` (ADR-058 D2).

Layer: adapters/config (TOML parsing is I/O at the boundary — mirrors
`agent_definitions_loader.py`).
Constitutional home: 06_MEMORY Part XI (recipes are config, versioned),
05_AGENTS AG-009. Recipes ship inside the package and are never hand-edited,
so a malformed one is a defect in the shipped code: `RecipeInvalid` refuses
boot, the same posture `agent_definitions_loader.py` takes.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from kang.domain.ports.context_recipe import CLEARANCES, ContextRecipe
from kang.domain.ports.memory_store import MEMORY_TYPES

__all__ = ["RecipeInvalid", "discover_recipes", "parse_recipe"]

_WEIGHT_KEYS = ("semantic", "lexical", "recency", "importance", "context")


class RecipeInvalid(Exception):
    """A shipped recipe file is malformed. Boot-refusing."""


def _require(condition: bool, context: str, message: str) -> None:
    if not condition:
        raise RecipeInvalid(f"{context}: {message}")


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def parse_recipe(toml_text: str, context: str) -> ContextRecipe:
    try:
        data = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError as exc:
        raise RecipeInvalid(f"{context}: not valid TOML: {exc}") from exc
    for key in ("id", "view", "clearance"):
        _require(isinstance(data.get(key), str) and data[key], context, f"'{key}'")
    for key in ("version", "tier_floor", "budget_tokens", "k"):
        value = data.get(key)
        _require(
            isinstance(value, int) and not isinstance(value, bool) and value >= 0,
            context,
            f"'{key}' must be a non-negative integer",
        )
    types = data.get("types")
    _require(
        isinstance(types, list) and types and set(types) <= set(MEMORY_TYPES),
        context,
        f"'types' must be a non-empty subset of {MEMORY_TYPES}",
    )
    _require(data["clearance"] in CLEARANCES, context, f"clearance in {CLEARANCES}")
    _require(data["tier_floor"] <= 2, context, "'tier_floor' must be 0, 1 or 2")
    floor = data.get("confidence_floor")
    _require(_number(floor) and 0 <= floor <= 1, context, "'confidence_floor'")
    weights = data.get("weights", {})
    _require(
        isinstance(weights, dict)
        and set(weights) <= set(_WEIGHT_KEYS)
        and all(_number(v) and v >= 0 for v in weights.values()),
        context,
        f"'weights' may override only {_WEIGHT_KEYS}, non-negative",
    )
    return ContextRecipe(
        id=data["id"],
        version=data["version"],
        view=data["view"],
        types=tuple(types),
        clearance=data["clearance"],
        tier_floor=data["tier_floor"],
        confidence_floor=float(floor),
        budget_tokens=data["budget_tokens"],
        k=data["k"],
        weights={k: float(v) for k, v in weights.items()},
    )


def discover_recipes(directory: Path) -> dict[str, ContextRecipe]:
    """Every `*.toml` in `directory`, keyed by recipe id; the file stem must
    equal the id, and ids are unique."""
    recipes: dict[str, ContextRecipe] = {}
    for path in sorted(directory.glob("*.toml")):
        recipe = parse_recipe(path.read_text(encoding="utf-8"), path.name)
        _require(recipe.id == path.stem, path.name, "file name must equal its 'id'")
        recipes[recipe.id] = recipe
    return recipes
