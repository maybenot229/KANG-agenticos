"""The Phase 2 gate's manifest-determinism proof (03 §3 "first byte-identical
manifest determinism proof"; 18 §4; 13 §2.6 "same store snapshot + same
recipe ⇒ byte-identical context manifest"; 05 AG-009; ADR-058 D5).

Two copies of the same year-1 synthetic corpus snapshot, each embedded by
the worker with the deterministic fake provider, each read by its own,
independently built Context Assembler (real SQLite stores, a real Router, a
real PermissionEngine): the same recipe, query, clock and correlation id give
the same manifest bytes — and the manifest is not trivially empty.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.model_provider import FakeModelCallStore, FakeModelProvider
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.embedding_index import SqliteEmbeddingIndex
from kang.adapters.sqlite.memory_search import SqliteMemorySearchStore
from kang.domain.memory.embedding import run_embedding_pass
from kang.domain.ports.context_recipe import ContextRecipe
from kang.domain.ports.memory_config import (
    AssemblyConfig,
    ScoringConfig,
    ScoringWeights,
)
from kang.domain.ports.memory_store import MEMORY_TYPES
from kang.domain.ports.provider_config import ProviderEntry, ProvidersConfig
from kang.kernel.context.assembler import (
    AssemblerDeps,
    AssemblyRequest,
    ContextAssembler,
)
from kang.kernel.permissions.engine import PermissionEngine
from kang.kernel.router.router import Router

NOW = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
RECIPE = ContextRecipe(
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
SCORING = ScoringConfig(
    ScoringWeights(0.40, 0.20, 0.15, 0.15, 0.10),
    {t: 0.0 for t in MEMORY_TYPES} | {"fact": 180.0, "observation": 30.0},
    match_min_similarity=0.5,
)
SHARES = {"p0": 0.30, "p1": 0.15, "p2": 0.30, "p3": 0.15, "p4": 0.10}


def _router() -> Router:
    return Router(
        ProvidersConfig(
            chains={
                "embedding": (
                    ProviderEntry("ollama", "nomic-embed-text", local_only=True),
                )
            }
        ),
        {"ollama": FakeModelProvider()},
        FakeModelCallStore(),
        FakeClock(NOW),
    )


def _embedded_snapshot(corpus_path, target) -> None:
    """The corpus, embedded once by the worker — the snapshot both
    assemblers read (copied, never shared)."""
    source = open_connection(corpus_path)
    source.execute("VACUUM INTO ?", (str(target),))
    source.close()
    conn = open_connection(target)
    try:
        run_embedding_pass(SqliteEmbeddingIndex(conn), _router().embed, 5000)
    finally:
        conn.close()


def _assembler_over_a_copy(snapshot, target):
    source = open_connection(snapshot)
    source.execute("VACUUM INTO ?", (str(target),))
    source.close()
    conn = open_connection(target)
    assembler = ContextAssembler(
        AssemblerDeps(
            store=SqliteMemorySearchStore(conn),
            index=SqliteEmbeddingIndex(conn),
            embed=_router().embed,
            scoring=SCORING,
            assembly=AssemblyConfig(SHARES),
            recipes={RECIPE.id: RECIPE},
            permissions=PermissionEngine({"agent:chat": ("memory.read:chat-view",)}),
            clock=FakeClock(NOW),
        )
    )
    return conn, assembler


def test_two_assemblers_over_the_same_snapshot_write_the_same_bytes(
    corpus_year1, tmp_path
):
    query_conn = open_connection(corpus_year1.path)
    query = query_conn.execute(
        "SELECT content FROM memory_record WHERE status = 'active' "
        "AND sensitivity = 'normal' AND type = 'fact' ORDER BY id LIMIT 1"
    ).fetchone()[0]
    query_conn.close()

    snapshot = tmp_path / "snapshot.db"
    _embedded_snapshot(corpus_year1.path, snapshot)
    manifests = []
    for name in ("a.db", "b.db"):
        conn, assembler = _assembler_over_a_copy(snapshot, tmp_path / name)
        try:
            manifests.append(
                assembler.assemble(
                    AssemblyRequest("chat", RECIPE.id, query, "corr-gate")
                ).manifest
            )
        finally:
            conn.close()

    assert manifests[0] == manifests[1]
    parsed = json.loads(manifests[0])
    assert parsed["relevance"], "the proof must not pass on an empty manifest"
    assert parsed["standing"]
    assert parsed["semantic"] == "ok" and parsed["refused"] is None
    used = sum(parsed["budget"]["used"].values())
    assert 0 < used <= RECIPE.budget_tokens
