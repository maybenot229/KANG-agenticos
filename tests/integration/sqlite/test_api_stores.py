"""Sqlite API stores — invocation, idempotency, session (12 §4/§12, API-003/4).

The C4 gate exercises these end-to-end across a restart; here their specific
guarantees are pinned directly against the real adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.idempotency_store import SqliteIdempotencyStore
from kang.adapters.sqlite.invocation_store import SqliteInvocationStore
from kang.adapters.sqlite.migrations import apply_migrations
from kang.adapters.sqlite.session_store import SqliteSessionStore
from kang.domain.ports.invocation import Invocation, InvocationNotFound
from kang.domain.ports.session import Session, SessionInvalid

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"


@pytest.fixture
def conn(tmp_path):
    connection = open_connection(tmp_path / "kang.db")
    apply_migrations(connection, MIGRATIONS_DIR, FakeClock())
    yield connection
    connection.close()


def _invocation(correlation_id: str = "corr-1") -> Invocation:
    return Invocation(
        id="inv-1",
        correlation_id=correlation_id,
        kind="command",
        operation="task.create",
        principal="kang",
        trigger="cli",
        started="2026-01-01T00:00:00+00:00",
        finished=None,
        outcome=None,
    )


def test_invocation_start_finish_and_lookup_by_correlation(conn):
    store = SqliteInvocationStore(conn)
    store.start(_invocation())
    store.finish("inv-1", "ok", "2026-01-01T00:00:01+00:00")
    found = store.by_correlation("corr-1")
    assert found.outcome == "ok"
    assert found.operation == "task.create"


def test_invocation_unknown_correlation_raises(conn):
    with pytest.raises(InvocationNotFound):
        SqliteInvocationStore(conn).by_correlation("nope")


def test_idempotency_first_write_wins(conn):
    store = SqliteIdempotencyStore(conn)
    store.put("k1", '{"n": 1}', "2026-01-01T00:00:00+00:00")
    store.put("k1", '{"n": 2}', "2026-01-02T00:00:00+00:00")  # ignored
    assert store.get("k1") == '{"n": 1}'
    assert store.get("unseen") is None


def test_idempotency_retention_sweep(conn):
    store = SqliteIdempotencyStore(conn)
    store.put("old", "{}", "2026-01-01T00:00:00+00:00")
    store.put("new", "{}", "2026-01-10T00:00:00+00:00")
    assert store.purge_before("2026-01-05T00:00:00+00:00") == 1
    assert store.get("old") is None and store.get("new") is not None


def test_session_resolve_and_invalid(conn):
    store = SqliteSessionStore(conn)
    store.create(
        Session(token="tok", principal="kang", first_party=True, created_at="t")
    )
    resolved = store.resolve("tok")
    assert resolved.principal == "kang" and resolved.first_party is True
    with pytest.raises(SessionInvalid):
        store.resolve("ghost")
