"""Context recipes (ADR-058 D2): the shipped recipe loads; a malformed
recipe refuses boot rather than degrading."""

from __future__ import annotations

from pathlib import Path

import pytest

from kang.adapters.config.recipes_loader import (
    RecipeInvalid,
    discover_recipes,
    parse_recipe,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
ASSEMBLY_DIR = REPO_ROOT / "src" / "kang" / "agents" / "assembly"

GOOD = """
id = "r"
version = 1
view = "r-view"
types = ["fact"]
clearance = "normal"
tier_floor = 0
confidence_floor = 0.0
budget_tokens = 100
k = 4
"""


def test_the_shipped_chat_recipe_loads():
    recipes = discover_recipes(ASSEMBLY_DIR)
    chat = recipes["chat-general"]
    assert (chat.view, chat.clearance, chat.version) == ("chat-view", "normal", 1)


@pytest.mark.parametrize(
    "broken",
    [
        GOOD.replace('types = ["fact"]', 'types = ["fact", "gossip"]'),
        GOOD.replace('clearance = "normal"', 'clearance = "private"'),
        GOOD.replace("tier_floor = 0", "tier_floor = 3"),
        GOOD.replace("confidence_floor = 0.0", "confidence_floor = 1.5"),
        GOOD.replace("k = 4", "k = -1"),
        GOOD + "weights = { charm = 0.5 }\n",
        GOOD.replace('view = "r-view"\n', ""),
    ],
)
def test_a_malformed_recipe_refuses(broken):
    assert broken != GOOD
    with pytest.raises(RecipeInvalid):
        parse_recipe(broken, "r.toml")


def test_a_recipe_file_must_be_named_for_its_id(tmp_path):
    (tmp_path / "other.toml").write_text(GOOD, encoding="utf-8")
    with pytest.raises(RecipeInvalid):
        discover_recipes(tmp_path)
