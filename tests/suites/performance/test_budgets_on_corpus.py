"""Performance budgets on the 10-year synthetic corpus (13 §2.12; 07 Part XIV:
"Exceeding a budget in CI is a failing build, not a warning"; ADR-049 D5).

Only the budgets measurable today. Named, not measured yet: hybrid candidate
fetch (needs `vec_*`), full index rebuild (no rebuild command), single-row
insert via the write queue (no memory store).

Method: one cold run (first execution on a freshly opened connection — SQLite's
page cache is empty; the OS file cache is not dropped) then a warm second run;
both are printed so the CI log keeps them (13 §2.12's slope tracking starts
from these numbers) and the assertion is on the warm one. Machine: whatever
runs the nightly tier; the number in the log is the only claim.

FTS scope, stated plainly: a "deep search" here is a two- or three-keyword
query, `ORDER BY rank LIMIT 20`, against `fts_chunk` (the largest index) and
`fts_memory`. The one-common-word query is measured and printed but NOT
asserted — with ~40% of chunks matching, ranking is proportional to the match
set, and 07 Part XIV does not say a single-stopword-like term is in budget.
That is a disclosed judgement, not a discovery.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.deadline_store import SqliteDeadlineStore
from kang.adapters.sqlite.migrations import apply_migrations
from kang.adapters.sqlite.task_store import SqliteTaskStore
from tests.fixtures.corpus.generate import MIGRATIONS_DIR

pytestmark = pytest.mark.nightly

# docs/07_DATABASE.md Part XIV latency budgets (line numbers as of 2026-09-21).
BUDGET_P0_VIEWS_S = 0.020  # :842  "Named P0 views (today, deadlines) < 20 ms"
BUDGET_LINK_DEPTH2_S = 0.010  # :845  "Recursive link query (depth 2) < 10 ms"
BUDGET_FTS_DEEP_S = 0.100  # :846  "FTS query (deep search) < 100 ms"
BUDGET_VACUUM_INTO_S = 60.0  # :847  "`VACUUM INTO` snapshot < 60 s"
BUDGET_STARTUP_S = 0.500  # :849  "Startup (open + pragma + version check) < 500 ms"

# 07 Part VII (docs/07_DATABASE.md:718), verbatim.
PART_VII_CTE = """
WITH RECURSIVE hop(node, depth) AS (
  SELECT :start, 0
  UNION
  SELECT li.dst, hop.depth + 1
  FROM link_index li JOIN hop ON li.src = hop.node
  WHERE hop.depth < :max_depth
)
SELECT DISTINCT node, MIN(depth) FROM hop GROUP BY node;
"""

# Pseudo-words drawn from the corpus's fixed syllable tail (text.py).
DEEP_CHUNK_QUERIES = ("olympiad baran", "deadline kesol mutik", "sermon lorun nuvax")
DEEP_MEMORY_QUERIES = ("olympiad baran", "deadline kesol")
BROAD_QUERY = "sermon"  # measured, printed, not asserted (module docstring)


@pytest.fixture(scope="module")
def conn(corpus_year10):
    connection = open_connection(corpus_year10.path)
    yield connection
    connection.close()


def measure(name: str, limit_s: float, fn: Callable[[], object]) -> float:
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


def _fts(conn, table: str, query: str) -> Callable[[], object]:
    sql = f"SELECT rowid FROM {table} WHERE {table} MATCH ? ORDER BY rank LIMIT 20"
    return lambda: conn.execute(sql, (query,)).fetchall()


@pytest.mark.parametrize("query", DEEP_CHUNK_QUERIES)
def test_fts_deep_search_over_chunks_is_within_budget(conn, query):
    warm = measure(
        f"fts_chunk '{query}'", BUDGET_FTS_DEEP_S, _fts(conn, "fts_chunk", query)
    )
    assert warm < BUDGET_FTS_DEEP_S


@pytest.mark.parametrize("query", DEEP_MEMORY_QUERIES)
def test_fts_deep_search_over_memory_is_within_budget(conn, query):
    warm = measure(
        f"fts_memory '{query}'", BUDGET_FTS_DEEP_S, _fts(conn, "fts_memory", query)
    )
    assert warm < BUDGET_FTS_DEEP_S


def test_fts_queries_actually_match_rows(conn):
    """A budget over an empty result proves nothing."""
    for query in DEEP_CHUNK_QUERIES:
        assert _fts(conn, "fts_chunk", query)(), query
    assert _fts(conn, "fts_memory", DEEP_MEMORY_QUERIES[0])()


def test_a_single_common_term_is_measured_but_not_asserted(conn):
    measure(
        f"fts_chunk '{BROAD_QUERY}' (informational)",
        BUDGET_FTS_DEEP_S,
        _fts(conn, "fts_chunk", BROAD_QUERY),
    )


def test_recursive_link_query_at_depth_2_is_within_budget(conn):
    start = conn.execute(
        "SELECT src FROM link_index GROUP BY src ORDER BY COUNT(*) DESC, src LIMIT 1"
    ).fetchone()[0]
    params = {"start": start, "max_depth": 2}
    reached = conn.execute(PART_VII_CTE, params).fetchall()
    assert len(reached) > 1, "the well-connected start node must reach other nodes"
    warm = measure(
        f"link depth-2 CTE (reaches {len(reached)} nodes)",
        BUDGET_LINK_DEPTH2_S,
        lambda: conn.execute(PART_VII_CTE, params).fetchall(),
    )
    assert warm < BUDGET_LINK_DEPTH2_S


def test_p0_reads_via_the_real_stores_are_within_budget(conn):
    tasks = SqliteTaskStore(conn, FakeClock())
    deadlines = SqliteDeadlineStore(conn, FakeClock())
    assert tasks.plannable() and deadlines.active()
    for name, fn in (
        ("TaskStore.plannable", tasks.plannable),
        ("DeadlineStore.active", deadlines.active),
    ):
        assert measure(name, BUDGET_P0_VIEWS_S, fn) < BUDGET_P0_VIEWS_S


def test_vacuum_into_snapshot_is_within_budget(conn, tmp_path):
    def snapshot() -> None:
        target = tmp_path / "snapshot.db"
        target.unlink(missing_ok=True)
        conn.execute(f"VACUUM INTO '{target}'")

    assert measure("VACUUM INTO", BUDGET_VACUUM_INTO_S, snapshot) < BUDGET_VACUUM_INTO_S


def test_startup_open_pragma_and_version_check_is_within_budget(corpus_year10):
    def startup() -> None:
        connection = open_connection(corpus_year10.path)  # PRAGMAs set and verified
        try:
            assert apply_migrations(connection, MIGRATIONS_DIR, FakeClock()) == []
        finally:
            connection.close()

    assert (
        measure("open+pragma+version check", BUDGET_STARTUP_S, startup)
        < BUDGET_STARTUP_S
    )
