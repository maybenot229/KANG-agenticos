"""The dual-index embedding protocol, end to end, on the year-1 synthetic corpus
— before any real embedding exists (03_ROADMAP §3: "dual-index protocol
tested before first real embedding"; 18 §4; 07 Part XVI "Vector correctness:
kNN sanity fixtures; version-migration protocol end-to-end"; ADR-055 D8).

Real migrated schema, real SqliteEmbeddingIndex, real Router; only the
provider is a fake (deterministic vectors, no network). A `v2` is applied the
way a future model-change migration would apply it.
"""

from __future__ import annotations

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.model_provider import (
    FakeModelCallStore,
    FakeModelProvider,
    fake_vector,
)
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.embedding_index import SqliteEmbeddingIndex
from kang.domain.memory.embedding import run_embedding_pass
from kang.domain.ports.embedding_index import EmbeddingVersion
from kang.domain.ports.provider_config import ProviderEntry, ProvidersConfig
from kang.kernel.router.router import Router


@pytest.fixture
def conn(corpus_year1, tmp_path):
    # The session corpus is shared: work on a copy, never the original.
    source = open_connection(corpus_year1.path)
    copy = tmp_path / "kang.db"
    source.execute("VACUUM INTO ?", (str(copy),))
    source.close()
    connection = open_connection(copy)
    yield connection
    connection.close()


def _router(model: str, provider: FakeModelProvider) -> Router:
    return Router(
        ProvidersConfig(
            chains={"embedding": (ProviderEntry("ollama", model, local_only=True),)}
        ),
        {"ollama": provider},
        FakeModelCallStore(),
        FakeClock(),
    )


def _drain(index, router, batch_size: int, limit: int = 50):
    results = []
    for _ in range(limit):
        result = run_embedding_pass(index, router.embed, batch_size)
        results.append(result)
        if result.embedded == 0 and not result.cut_over:
            break
    return results


def test_version_one_fills_the_whole_corpus_and_knn_finds_each_record(conn):
    index = SqliteEmbeddingIndex(conn)
    _drain(index, _router("nomic-embed-text", FakeModelProvider()), 2000)
    coverage = index.memory_coverage(1)
    assert coverage.embeddable > 1000 and coverage.is_complete

    sample = conn.execute(
        "SELECT id, content FROM memory_record WHERE status = 'active' "
        "AND sensitivity <> 'private' ORDER BY id LIMIT 5"
    ).fetchall()
    for record_id, content in sample:
        (nearest,) = index.nearest_memory(1, fake_vector(content, 768), 1)
        nearest_content = conn.execute(
            "SELECT content FROM memory_record WHERE id = ?", (nearest.record_id,)
        ).fetchone()[0]
        # Equal content embeds identically; the corpus may repeat a sentence.
        assert nearest_content == content
        assert nearest.distance == pytest.approx(0.0, abs=1e-5)


def test_a_model_change_migrates_without_a_blackout_and_cuts_over_once(conn):
    index = SqliteEmbeddingIndex(conn)
    _drain(index, _router("nomic-embed-text", FakeModelProvider()), 2000)
    embeddable = index.memory_coverage(1).embeddable

    # What a model-change migration does (ADR-055 D4): register v2 and its
    # table. providers.toml then serves the new model.
    conn.execute(
        "INSERT INTO embedding_version VALUES "
        "(2, 'next-model', 16, '2026-10-05T00:00:00.000Z', 'migrating')"
    )
    conn.execute(
        "CREATE VIRTUAL TABLE vec_memory_v2 USING vec0("
        "record_rowid INTEGER PRIMARY KEY, embedding float[16] distance_metric=cosine)"
    )
    provider = FakeModelProvider()
    provider.embed_dim = 16
    router = _router("next-model", provider)

    first = run_embedding_pass(index, router.embed, 500)
    # v1 is complete, so nothing of it is pending and nothing is "unserved";
    # the whole budget goes to v2, and no cutover happens yet.
    assert first.embedded == 500 and first.cut_over == ()
    # Mid-migration: v1 is still complete and still the space queries read.
    assert index.memory_coverage(1).is_complete
    assert index.versions_to_fill()[0] == EmbeddingVersion(
        1, "nomic-embed-text", 768, "active"
    )
    probe = conn.execute(
        "SELECT content FROM memory_record WHERE status = 'active' "
        "AND sensitivity <> 'private' ORDER BY id LIMIT 1"
    ).fetchone()[0]
    assert index.nearest_memory(1, fake_vector(probe, 768), 1)[0].distance < 1e-5

    results = _drain(index, router, 500)
    cutovers = [ver for r in [first, *results] for ver in r.cut_over]
    assert cutovers == [2]
    assert index.versions_to_fill() == (
        EmbeddingVersion(2, "next-model", 16, "active"),
    )
    coverage = index.memory_coverage(2)
    assert coverage.is_complete and coverage.embeddable == embeddable
    assert conn.execute(
        "SELECT status FROM embedding_version WHERE ver = 1"
    ).fetchone() == ("retired",)
