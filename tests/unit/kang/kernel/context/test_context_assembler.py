"""The Context Assembler (ADR-058) against fakes, through a real Router and a
real PermissionEngine — 05 §16's Context suite: recipe determinism,
truncation order, privacy filters, plus scope enforcement and the manifest's
content-free shape."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.embedding_index import FakeEmbeddingIndex
from kang.adapters.fakes.memory_search import FakeMemorySearchStore
from kang.adapters.fakes.memory_store import FakeMemoryStore
from kang.adapters.fakes.model_provider import FakeModelCallStore, FakeModelProvider
from kang.domain.memory.assembly import (
    AssemblyItem,
    allocate,
    estimate_tokens,
    render_line,
)
from kang.domain.memory.embedding import run_embedding_pass
from kang.domain.ports.context_recipe import ContextRecipe, RecipeNotFound
from kang.domain.ports.memory_config import (
    AssemblyConfig,
    ScoringConfig,
    ScoringWeights,
)
from kang.domain.ports.memory_store import MEMORY_TYPES
from kang.domain.ports.model_provider import ProviderUnavailable
from kang.domain.ports.provider_config import ProviderEntry, ProvidersConfig
from kang.kernel.context.assembler import (
    AssemblerDeps,
    AssemblyRequest,
    ContextAssembler,
)
from kang.kernel.permissions.engine import PermissionEngine
from kang.kernel.router.router import Router
from tests.fixtures.memory_store_contract import record

NOW = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
SHARES = {"p0": 0.30, "p1": 0.15, "p2": 0.30, "p3": 0.15, "p4": 0.10}
SCORING = ScoringConfig(
    ScoringWeights(0.40, 0.20, 0.15, 0.15, 0.10),
    {t: 0.0 for t in MEMORY_TYPES},
    match_min_similarity=0.5,
    stopwords=frozenset({"the", "what", "do", "i", "about"}),
)


def recipe(**overrides) -> ContextRecipe:
    base = dict(
        id="chat-general",
        version=1,
        view="chat-view",
        types=MEMORY_TYPES,
        clearance="normal",
        tier_floor=0,
        confidence_floor=0.0,
        budget_tokens=1200,
        k=8,
    )
    base.update(overrides)
    return ContextRecipe(**base)


class World:
    def __init__(self, grants=None, **recipe_overrides) -> None:
        self.memory = FakeMemoryStore()
        self.index = FakeEmbeddingIndex(self.memory)
        self.provider = FakeModelProvider()
        self.router = Router(
            ProvidersConfig(
                chains={
                    "embedding": (
                        ProviderEntry("ollama", "nomic-embed-text", local_only=True),
                    )
                }
            ),
            {"ollama": self.provider},
            FakeModelCallStore(),
            FakeClock(NOW),
        )
        self.assembler = ContextAssembler(
            AssemblerDeps(
                store=FakeMemorySearchStore(self.memory),
                index=self.index,
                embed=self.router.embed,
                scoring=SCORING,
                assembly=AssemblyConfig(SHARES),
                recipes={"chat-general": recipe(**recipe_overrides)},
                permissions=PermissionEngine(
                    grants
                    if grants is not None
                    else {"agent:chat": ("memory.read:chat-view",)}
                ),
                clock=FakeClock(NOW),
            )
        )

    def save(self, record_id: str, content: str, **overrides) -> None:
        self.memory.insert_record(record(id=record_id, content=content, **overrides))

    def embed_all(self) -> None:
        run_embedding_pass(self.index, self.router.embed, 100)

    def assemble(self, query: str = "robotics team", correlation_id: str = "corr-1"):
        result = self.assembler.assemble(
            AssemblyRequest("chat", "chat-general", query, correlation_id)
        )
        return result, json.loads(result.manifest)


# ---- the pure core -----------------------------------------------------------


def test_a_line_is_06s_mem_block_and_contested_records_are_flagged():
    r = record(id="m1", content="term ends in June", source_kind="stated")
    assert render_line(r) == "[MEM:m1] term ends in June — stated, 2026-09-21, tier 2"
    contested = record(id="m2", content="x", status="under_review")
    assert render_line(contested).startswith("⚠ [MEM:m2]")


def _items(klass: str, sizes: list[int]) -> list[AssemblyItem]:
    out = []
    for n, size in enumerate(sizes):
        r = record(id=f"{klass}-{n}", content="x" * (size * 4))
        out.append(AssemblyItem(r, klass, "relevance", None, "", size))
    return out


def test_unused_budget_cascades_down_and_truncation_is_bottom_up():
    # 100 tokens: p0 30 unused carries -> p1 15+30=45 holds 20+20, carries 5
    # -> p2 30+5=35 holds 30, cuts 40 -> what is left carries on.
    items = _items("p1", [20, 20, 20]) + _items("p2", [30, 40])
    allocation = allocate(items, 100, SHARES)
    included = [i.record.id for i in allocation.included]
    assert included == ["p1-0", "p1-1", "p2-0"]
    assert [i.record.id for i in allocation.truncated] == ["p1-2", "p2-1"]
    assert allocation.allowance["p1"] == 45 and allocation.used["p1"] == 40


def test_allocation_never_exceeds_the_budget_and_keeps_rank_order():
    for budget in range(0, 400, 7):
        items = _items("p1", [5, 9, 13, 2]) + _items("p2", [11, 3, 17, 8, 1])
        allocation = allocate(items, budget, SHARES)
        assert sum(i.tokens for i in allocation.included) <= budget
        for klass in ("p1", "p2"):
            ranked = [i.record.id for i in items if i.klass == klass]
            kept = [i.record.id for i in allocation.included if i.klass == klass]
            assert kept == ranked[: len(kept)]  # a prefix: bottom-up cuts only


def test_token_estimate_is_deterministic():
    assert estimate_tokens("abcd" * 10) == 11


# ---- the kernel assembler ----------------------------------------------------


def test_rules_are_always_first_then_pinned_then_profile_and_preference():
    w = World()
    w.save("z-rule", "never schedule deep work before nine", type="rule")
    w.save("a-pref", "prefers markdown reports", type="preference")
    w.save("b-pin", "robotics team meets fridays", pinned=True)
    w.save("c-fact", "school term ends in june")
    result, manifest = w.assemble("anything at all")
    standing = [(e["id"], e["why"]) for e in manifest["standing"]]
    assert standing == [
        ("z-rule", "rule"),
        ("b-pin", "pinned"),
        ("a-pref", "preference"),
    ]
    assert result.context.splitlines()[0].startswith("[MEM:z-rule]")


def test_relevance_comes_from_the_hybrid_search_and_skips_standing_records():
    w = World()
    w.save("p", "robotics team mentor", pinned=True)
    w.save("f", "the robotics team meets on friday")
    w.save("x", "school term ends in june")
    w.embed_all()
    _, manifest = w.assemble("robotics team")
    assert [e["id"] for e in manifest["relevance"]] == ["f"]
    assert set(manifest["relevance"][0]["terms"]) == {
        "semantic",
        "lexical",
        "recency",
        "importance",
        "context",
    }


def test_no_grant_means_no_read_and_a_recorded_refusal():
    w = World(grants={})
    w.save("r", "a rule", type="rule")
    result, manifest = w.assemble()
    assert manifest["refused"] == "scope"
    assert manifest["standing"] == [] and manifest["relevance"] == []
    assert result.context == "(nothing relevant in memory)"


def test_a_sensitive_clearance_needs_its_own_grant():
    w = World(clearance="sensitive")
    _, manifest = w.assemble()
    assert manifest["refused"] == "scope"


def test_sensitive_and_private_records_never_reach_a_normal_clearance_recipe():
    w = World()
    w.save("s", "robotics grades", sensitivity="sensitive", type="rule")
    w.save("p", "[encrypted]", sensitivity="private", content_enc=b"c", type="rule")
    w.save("n", "robotics rule", type="rule")
    result, manifest = w.assemble("robotics")
    assert [e["id"] for e in manifest["standing"]] == ["n"]
    # Judged once, counted once (found by both the standing read and the
    # search); private is never even fetched.
    assert manifest["suppressed"] == {"sensitivity": 1}
    assert "grades" not in result.context


def test_type_tier_and_confidence_floors_suppress_with_their_reason():
    w = World(types=("rule", "fact"), tier_floor=1, confidence_floor=0.5)
    w.save("pref", "a preference", type="preference")
    w.save("low-tier", "a low tier rule", type="rule", trust_tier=0)
    w.save("low-conf", "an unsure rule", type="rule", confidence=0.2)
    w.save("ok", "a rule", type="rule")
    _, manifest = w.assemble("nothing")
    assert [e["id"] for e in manifest["standing"]] == ["ok"]
    assert manifest["suppressed"] == {"confidence": 1, "tier": 1, "type": 1}


def test_the_manifest_is_content_free():
    w = World()
    w.save("r", "a very private sounding rule", type="rule")
    result, _ = w.assemble("my secret question")
    assert "private sounding" not in result.manifest
    assert "secret question" not in result.manifest
    assert "private sounding" in result.context


def test_same_inputs_give_byte_identical_manifests():
    # 13 §2.6 / AG-009 / the Phase 2 gate: same recipe version, query, store
    # snapshot, clock and correlation id => the same bytes.
    w = World()
    for i in range(12):
        w.save(f"m{i:02d}", f"robotics fact number {i}", pinned=i % 5 == 0)
    w.save("rule", "a standing rule", type="rule")
    w.embed_all()
    first = w.assemble("robotics fact", "corr-9")[0].manifest
    second = w.assemble("robotics fact", "corr-9")[0].manifest
    assert first == second
    assert json.loads(first)["recipe"] == {"id": "chat-general", "version": 1}


def test_an_unknown_recipe_is_a_loud_wiring_defect():
    w = World()
    with pytest.raises(RecipeNotFound):
        w.assembler.assemble(AssemblyRequest("chat", "nope", "q", "c"))


def test_an_unavailable_embedder_still_assembles_lexically():
    w = World()
    w.save("f", "robotics team meets friday")
    w.provider.embed_errors.append(ProviderUnavailable("ollama closed"))
    _, manifest = w.assemble("robotics")
    assert manifest["semantic"] == "unavailable"
    assert [e["id"] for e in manifest["relevance"]] == ["f"]
    assert manifest["deterministic"] == {"items": [], "reason": "not_built"}
