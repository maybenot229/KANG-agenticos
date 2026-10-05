"""The embedding worker's policy (ADR-055 D7/D8) against fakes, through a real
Router (so the `model_call` ledger and the privacy filter are exercised, not
assumed) — zero network."""

from __future__ import annotations

from tests.fixtures.memory_store_contract import record

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.embedding_index import FakeEmbeddingIndex
from kang.adapters.fakes.memory_store import FakeMemoryStore
from kang.adapters.fakes.model_provider import FakeModelCallStore, FakeModelProvider
from kang.domain.memory.embedding import run_embedding_pass
from kang.domain.ports.embedding_index import EmbeddingVersion
from kang.domain.ports.model_provider import ProviderUnavailable
from kang.domain.ports.provider_config import ProviderEntry, ProvidersConfig
from kang.kernel.router.router import Router


class World:
    def __init__(self, model: str = "nomic-embed-text", chain: bool = True) -> None:
        self.memory = FakeMemoryStore()
        self.index = FakeEmbeddingIndex(self.memory)
        self.provider = FakeModelProvider()
        self.calls = FakeModelCallStore()
        entries = (ProviderEntry("ollama", model, local_only=True),) if chain else ()
        self.router = Router(
            ProvidersConfig(chains={"embedding": entries}),
            {"ollama": self.provider},
            self.calls,
            FakeClock(),
        )

    def seed(self, count: int, **overrides) -> None:
        for i in range(count):
            self.memory.insert_record(
                record(
                    id=f"{overrides.get('prefix', 'mem')}-{i}",
                    content=f"assertion {overrides.get('prefix', '')} {i}",
                    updated_at=f"2026-09-01T10:{i:02d}:00+00:00",
                    sensitivity=overrides.get("sensitivity", "normal"),
                    content_enc=overrides.get("content_enc"),
                )
            )

    def run(self, batch_size: int = 8):
        return run_embedding_pass(self.index, self.router.embed, batch_size)


def test_one_pass_embeds_at_most_the_batch_newest_first():
    world = World()
    world.seed(10)
    result = world.run(batch_size=8)
    assert result.embedded == 8 and result.degraded is None
    pending = [p.record_id for p in world.index.pending_memory(1, 10)]
    assert pending == ["mem-1", "mem-0"]  # the two oldest wait for the next pass
    assert {c.task_class for c in world.calls.calls} == {"embedding"}


def test_repeated_passes_drain_the_backlog_then_do_nothing():
    world = World()
    world.seed(10)
    assert [world.run().embedded for _ in range(3)] == [8, 2, 0]
    assert world.index.memory_coverage(1).is_complete


def test_private_records_are_never_sent_to_any_provider():
    world = World()
    world.seed(2, prefix="secret", sensitivity="private", content_enc=b"x")
    world.seed(1)
    world.run()
    sent = [text for _, _, texts in world.provider.embed_calls for text in texts]
    assert all("secret" not in text for text in sent) and len(sent) == 1


def test_sensitive_records_travel_with_their_own_privacy_tier():
    world = World()
    world.seed(1, prefix="health", sensitivity="sensitive")
    world.seed(1)
    world.run()
    tiers = sorted(spec.privacy_tier for spec, _, _ in world.provider.embed_calls)
    assert tiers == ["normal", "sensitive"]


def test_an_unreachable_provider_is_a_declared_degraded_pass():
    world = World()
    world.seed(3)
    world.provider.embed_errors.append(ProviderUnavailable("ollama is closed"))
    result = world.run()
    assert (result.embedded, result.degraded) == (0, "provider_unavailable")
    assert world.index.memory_coverage(1).embedded == 0


def test_no_configured_provider_is_also_degraded_not_a_crash():
    world = World(chain=False)
    world.seed(1)
    assert world.run().degraded == "provider_unavailable"


def test_a_model_matching_no_version_stores_nothing_and_says_so():
    world = World()
    world.seed(2)
    world.provider.embed_echo_model = "some-other-model"
    result = world.run()
    assert result.embedded == 0 and "some-other-model" in result.mismatch
    assert world.index.memory_coverage(1).embedded == 0


def test_a_wrong_dimension_stores_nothing_and_says_so():
    world = World()
    world.seed(2)
    world.provider.embed_dim = 384
    result = world.run()
    assert result.embedded == 0 and "768" in result.mismatch


def test_a_migration_fills_the_new_space_and_cuts_over_only_when_complete():
    # DB-004's protocol: providers.toml serves the NEW model, so the active
    # version is unserved (its new rows wait on FTS); the migrating version
    # fills; cutover happens at full coverage, never before.
    world = World(model="next-model")
    world.seed(5)
    world.index.add_version(EmbeddingVersion(2, "next-model", 768, "migrating"))
    first = world.run(batch_size=3)
    assert (first.unserved, first.embedded, first.cut_over) == ((1,), 3, ())
    assert [v.ver for v in world.index.versions_to_fill()] == [1, 2]
    second = world.run(batch_size=3)
    assert (second.embedded, second.cut_over) == (2, (2,))
    assert world.index.versions_to_fill() == (
        EmbeddingVersion(2, "next-model", 768, "active"),
    )
