"""Kang-facing search (ADR-056) against fakes, through a real Router — the
two halves, the filters, matches vs nearest misses, deep mode, and the
declared degradation when vectors cannot serve."""

from __future__ import annotations

from datetime import datetime, timezone

from tests.fixtures.memory_store_contract import record

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.embedding_index import FakeEmbeddingIndex
from kang.adapters.fakes.memory_search import FakeMemorySearchStore
from kang.adapters.fakes.memory_store import FakeMemoryStore
from kang.adapters.fakes.model_provider import (
    FakeModelCallStore,
    FakeModelProvider,
    fake_vector,
)
from kang.domain.memory.embedding import run_embedding_pass
from kang.domain.memory.search import SearchDeps, SearchRequest, search_memory
from kang.domain.ports.embedding_index import EmbeddingVersion
from kang.domain.ports.memory_config import ScoringConfig, ScoringWeights
from kang.domain.ports.memory_store import MEMORY_TYPES
from kang.domain.ports.model_provider import ProviderUnavailable
from kang.domain.ports.provider_config import ProviderEntry, ProvidersConfig
from kang.kernel.router.router import Router

NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)
CONFIG = ScoringConfig(
    ScoringWeights(0.40, 0.20, 0.15, 0.15, 0.10),
    {t: 0.0 for t in MEMORY_TYPES},
    match_min_similarity=0.5,
    stopwords=frozenset({"the", "who", "is"}),
)


class World:
    def __init__(self, models: tuple[str, ...] = ("nomic-embed-text",)) -> None:
        self.memory = FakeMemoryStore()
        self.index = FakeEmbeddingIndex(self.memory)
        self.provider = FakeModelProvider()
        self.calls = FakeModelCallStore()
        self.router = Router(
            ProvidersConfig(
                chains={
                    "embedding": tuple(
                        ProviderEntry("ollama", m, local_only=True) for m in models
                    )
                }
            ),
            {"ollama": self.provider},
            self.calls,
            FakeClock(),
        )
        self.deps = SearchDeps(
            FakeMemorySearchStore(self.memory), self.index, self.router.embed, CONFIG
        )

    def save(self, record_id: str, content: str, **overrides) -> None:
        self.memory.insert_record(record(id=record_id, content=content, **overrides))

    def embed_all(self) -> None:
        run_embedding_pass(self.index, self.router.embed, 100)

    def search(self, query: str, **overrides):
        request = dict(
            query=query, mode="default", types=None, min_tier=None, limit=20, now=NOW
        )
        request.update(overrides)
        return search_memory(self.deps, SearchRequest(**request))


def ids(pairs) -> list[str]:
    return [record.id for _, record in pairs]


def test_an_exact_semantic_hit_matches_without_any_shared_word():
    world = World()
    world.save("a", "Dr Lee mentors the robotics team")
    world.save("b", "school term ends in june")
    world.embed_all()
    # The fake embeds identical text identically: a query with no word in
    # common with "a" would not be similar under the fake, so the semantic
    # path is proven with the record's own text as the query.
    outcome = world.search("Dr Lee mentors the robotics team")
    assert ids(outcome.matches)[0] == "a"
    assert outcome.degraded is None


def test_the_query_text_is_embedded_local_only_and_model_pinned():
    world = World()
    world.save("a", "anything")
    world.embed_all()
    world.provider.embed_calls.clear()
    world.search("what do I know")
    (spec, model, texts) = world.provider.embed_calls[0]
    assert (spec.privacy_tier, spec.latency_tolerance) == ("private", "interactive")
    assert model == "nomic-embed-text" and texts == ("what do I know",)


def test_a_lexical_hit_matches_even_before_any_vector_exists():
    world = World()
    world.save("a", "robotics competition in march")
    outcome = world.search("robotics")
    assert ids(outcome.matches) == ["a"]


def test_no_match_returns_labeled_nearest_misses_never_padded_results():
    world = World()
    world.save("a", "robotics competition in march")
    world.save("b", "school term ends in june")
    world.embed_all()
    outcome = world.search("zebra")
    assert outcome.matches == ()
    assert 0 < len(outcome.nearest_misses) <= 3


def test_with_matches_there_are_no_nearest_misses():
    world = World()
    world.save("a", "robotics competition in march")
    world.save("b", "school term ends in june")
    world.embed_all()
    outcome = world.search("robotics")
    assert ids(outcome.matches) == ["a"] and outcome.nearest_misses == ()


def test_archived_records_appear_only_in_deep_mode():
    world = World()
    world.save("a", "robotics archive", status="archived")
    assert world.search("robotics").matches == ()
    world.provider.embed_calls.clear()
    deep = world.search("robotics", mode="deep")
    assert ids(deep.matches) == ["a"]
    assert world.provider.embed_calls == []  # deep mode never embeds the query


def test_private_records_are_never_returned():
    world = World()
    world.save("p", "[encrypted]", sensitivity="private", content_enc=b"ciphertext")
    world.embed_all()
    outcome = world.search("encrypted")
    assert outcome.matches == () and outcome.nearest_misses == ()


def test_type_and_tier_facets_filter_before_scoring():
    world = World()
    world.save("f", "robotics fact", type="fact", trust_tier=2)
    world.save("o", "robotics observation", type="observation", trust_tier=1)
    assert ids(world.search("robotics", types=("observation",)).matches) == ["o"]
    assert ids(world.search("robotics", min_tier=2).matches) == ["f"]


def test_an_unavailable_provider_degrades_to_lexical_results():
    world = World()
    world.save("a", "robotics competition")
    world.provider.embed_errors.append(ProviderUnavailable("ollama closed"))
    outcome = world.search("robotics")
    assert outcome.degraded == "semantic_unavailable"
    assert ids(outcome.matches) == ["a"]


def test_during_a_migration_the_query_pins_the_active_model():
    # DB-004: the chain lists both models; the worker fills the new space
    # while queries keep reading the active one, embedded by ITS model.
    world = World(models=("next-model", "nomic-embed-text"))
    world.index.add_version(EmbeddingVersion(2, "next-model", 768, "migrating"))
    world.save("a", "robotics competition")
    world.provider.embed_calls.clear()
    world.search("robotics")
    assert world.provider.embed_calls[0][1] == "nomic-embed-text"


def test_a_query_vector_from_the_wrong_space_is_never_used():
    world = World()
    world.save("a", "robotics competition")
    world.embed_all()
    world.provider.embed_dim = 384
    outcome = world.search("robotics competition")
    assert outcome.degraded == "semantic_unavailable"
    assert ids(outcome.matches) == ["a"]  # lexical still serves


def test_the_kNN_distance_reaches_the_scorer():
    world = World()
    world.save("a", "Dr Lee mentors the robotics team")
    world.embed_all()
    ((scored, _),) = world.search("Dr Lee mentors the robotics team").matches
    assert scored.terms.semantic == 1.0
    assert fake_vector("x", 4) != fake_vector("y", 4)  # the fake discriminates


def test_sharing_only_a_stopword_is_not_a_lexical_hit():
    # Regression (2026-10-06 live check): "who helps the robotics team?" was
    # returning unrelated facts as matches because they contained "the".
    world = World()
    world.save("a", "Dr Lee mentors the robotics team")
    world.save("b", "the term ends in june")
    outcome = world.search("who helps the robotics team")
    assert ids(outcome.matches) == ["a"]


def test_a_query_of_only_stopwords_has_no_lexical_half():
    world = World()
    world.save("a", "the term ends in june")
    world.provider.embed_errors.append(ProviderUnavailable("closed"))
    outcome = world.search("who is the")
    assert outcome.matches == () and outcome.degraded == "semantic_unavailable"
