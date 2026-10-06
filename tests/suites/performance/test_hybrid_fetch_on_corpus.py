"""The hybrid candidate fetch and scoring budgets on the 10-year corpus
(ADR-056 D1; 13 §2.12; 07 Part XIV: "Exceeding a budget in CI is a failing
build, not a warning").

The year10 corpus holds no vectors (vectors are the embedding worker's), so
this suite works on a copy and fills `vec_memory_v1` with the deterministic
fake vectors first — the fetch's cost depends on row count and dimension,
not on what the vectors mean. Same cold-then-warm method and printed numbers
as `test_budgets_on_corpus.py`.

History, kept because it is why this suite exists in this form: ADR-056
first chose exact float kNN on a bare-kNN measurement (217-239 ms). This
suite's first run measured the whole fetch at 258-288 ms — red — which fired
ADR-056 D1's named remedy: ADR-057's int8 companion index, which kNN now
reads. Hardware: whatever runs the nightly tier; the printed numbers are the
only claim (07 Part XIV states its laptop assumption).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from kang.adapters.fakes.model_provider import fake_vector
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.embedding_index import SqliteEmbeddingIndex
from kang.adapters.sqlite.memory_search import SqliteMemorySearchStore
from kang.domain.memory.retrieval import RetrievalCandidate, score_candidates
from kang.domain.ports.embedding_index import EMBEDDABLE_STATUSES, VectorWrite
from kang.domain.ports.memory_config import ScoringConfig, ScoringWeights
from kang.domain.ports.memory_store import MEMORY_TYPES

pytestmark = pytest.mark.nightly

# docs/07_DATABASE.md:848 "Hybrid candidate fetch (vec k=64 + FTS k=64 +
# prefilter) < 250 ms"; docs/06_MEMORY.md:554 "Hybrid relevance (k=64
# candidates → scored) < 300 ms".
BUDGET_HYBRID_FETCH_S = 0.250
BUDGET_HYBRID_SCORED_S = 0.300
QUERIES = ("deadline kesol", "olympiad baran")
CONFIG = ScoringConfig(
    ScoringWeights(0.40, 0.20, 0.15, 0.15, 0.10),
    {t: 0.0 for t in MEMORY_TYPES} | {"fact": 180.0, "observation": 30.0},
    match_min_similarity=0.5,
)
NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def conn(corpus_year10, tmp_path_factory):
    source = open_connection(corpus_year10.path)
    copy = tmp_path_factory.mktemp("hybrid") / "kang.db"
    source.execute("VACUUM INTO ?", (str(copy),))
    source.close()
    connection = open_connection(copy)
    index = SqliteEmbeddingIndex(connection)
    while pending := index.pending_memory(1, 5000):
        index.store_memory_vectors(
            1, [VectorWrite(p, fake_vector(p.content, 768)) for p in pending]
        )
    yield connection
    connection.close()


def _fetch(conn, query: str):
    index = SqliteEmbeddingIndex(conn)
    store = SqliteMemorySearchStore(conn)
    neighbors = index.nearest_memory(1, fake_vector(query, 768), 64)
    lexical = store.lexical(query, EMBEDDABLE_STATUSES, None, 64)
    ids = {n.record_id for n in neighbors} | {h.record_id for h in lexical}
    return neighbors, lexical, store.records(sorted(ids))


def _fetch_and_score(conn, query: str):
    neighbors, lexical, records = _fetch(conn, query)
    distance = {n.record_id: n.distance for n in neighbors}
    bm25 = {h.record_id: h.bm25 for h in lexical}
    return score_candidates(
        [
            RetrievalCandidate(
                r.id,
                r.type,
                datetime.fromisoformat(r.updated_at),
                r.importance,
                r.pinned,
                distance.get(r.id),
                bm25.get(r.id),
            )
            for r in records
        ],
        NOW,
        CONFIG,
    )


def _measure(name: str, limit_s: float, fn) -> float:
    started = time.perf_counter()
    fn()
    cold = time.perf_counter() - started
    started = time.perf_counter()
    fn()
    warm = time.perf_counter() - started
    print(
        f"[budget] {name}: cold={cold * 1000:.2f} ms warm={warm * 1000:.2f} ms "
        f"limit={limit_s * 1000:.0f} ms"
    )
    return warm


def test_the_corpus_is_fully_embedded_before_measuring(conn):
    coverage = SqliteEmbeddingIndex(conn).memory_coverage(1)
    assert coverage.is_complete and coverage.embeddable > 30_000


@pytest.mark.parametrize("query", QUERIES)
def test_hybrid_candidate_fetch_is_within_budget(conn, query):
    warm = _measure(
        f"hybrid fetch '{query}'", BUDGET_HYBRID_FETCH_S, lambda: _fetch(conn, query)
    )
    assert warm < BUDGET_HYBRID_FETCH_S


@pytest.mark.parametrize("query", QUERIES)
def test_hybrid_relevance_scored_is_within_budget(conn, query):
    warm = _measure(
        f"hybrid scored '{query}'",
        BUDGET_HYBRID_SCORED_S,
        lambda: _fetch_and_score(conn, query),
    )
    assert warm < BUDGET_HYBRID_SCORED_S
