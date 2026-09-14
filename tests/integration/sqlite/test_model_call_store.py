"""SqliteModelCallStore — the usage & cost ledger (D010, AG-008, 07_DATABASE §5.5)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.migrations import apply_migrations
from kang.adapters.sqlite.model_call_store import SqliteModelCallStore
from kang.domain.ports.model_call import ModelCall

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"


@pytest.fixture
def conn(tmp_path):
    connection = open_connection(tmp_path / "kang.db")
    apply_migrations(connection, MIGRATIONS_DIR, FakeClock())
    yield connection
    connection.close()


@pytest.fixture
def store(conn) -> SqliteModelCallStore:
    return SqliteModelCallStore(conn)


def _call(**overrides) -> ModelCall:
    base = dict(
        provider="anthropic",
        model="claude-haiku-4",
        task_class="routine",
        tokens_in=10,
        tokens_out=5,
        cost_usd=0.002,
        latency_ms=120,
        outcome="ok",
        at="2026-09-14T00:00:00Z",
    )
    base.update(overrides)
    return ModelCall(**base)


def test_record_persists_a_row(conn, store):
    store.record(_call())
    row = conn.execute(
        "SELECT provider, model, task_class, tokens_in, tokens_out, "
        "cost_usd, latency_ms, outcome, at FROM model_call"
    ).fetchone()
    assert row == (
        "anthropic", "claude-haiku-4", "routine", 10, 5, 0.002, 120, "ok",
        "2026-09-14T00:00:00Z",
    )


def test_multiple_calls_accumulate_as_separate_rows(conn, store):
    store.record(_call(outcome="ok"))
    store.record(_call(outcome="fallback"))
    store.record(_call(outcome="error"))
    count = conn.execute("SELECT COUNT(*) FROM model_call").fetchone()[0]
    assert count == 3


def test_rows_survive_reopen(tmp_path):
    first = open_connection(tmp_path / "kang.db")
    apply_migrations(first, MIGRATIONS_DIR, FakeClock())
    SqliteModelCallStore(first).record(_call())
    first.close()

    second = open_connection(tmp_path / "kang.db")
    count = second.execute("SELECT COUNT(*) FROM model_call").fetchone()[0]
    assert count == 1
    second.close()


def test_only_the_check_constrained_outcomes_are_accepted(conn, store):
    with pytest.raises(sqlite3.IntegrityError):
        store.record(_call(outcome="not-a-real-outcome"))
