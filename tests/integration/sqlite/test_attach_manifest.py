"""InvocationStore.attach_manifest over kang.db (ADR-058 D5): the manifest
lands on the invocation row for its correlation id, and an unknown id is a
typed failure, never a silent no-op."""

from __future__ import annotations

from pathlib import Path

import pytest

from kang.adapters.fakes.api_stores import FakeInvocationStore
from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.invocation_store import SqliteInvocationStore
from kang.adapters.sqlite.migrations import apply_migrations
from kang.domain.ports.invocation import Invocation, InvocationNotFound

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"


@pytest.fixture(params=["sqlite", "fake"])
def store(request, tmp_path):
    if request.param == "fake":
        yield FakeInvocationStore()
        return
    conn = open_connection(tmp_path / "kang.db")
    apply_migrations(conn, MIGRATIONS_DIR, FakeClock())
    yield SqliteInvocationStore(conn)
    conn.close()


def _start(store) -> None:
    store.start(
        Invocation(
            id="inv-1",
            correlation_id="corr-1",
            kind="command",
            operation="chat.send",
            principal="kang",
            trigger="ui",
            started="2026-10-07T09:00:00+00:00",
            finished=None,
            outcome=None,
        )
    )


def test_the_manifest_lands_on_the_invocation_and_survives_finish(store):
    _start(store)
    store.attach_manifest("corr-1", '{"schema":1}')
    store.finish("inv-1", "ok", "2026-10-07T09:00:01+00:00")
    assert store.by_correlation("corr-1").manifest == '{"schema":1}'


def test_an_unknown_correlation_id_is_refused(store):
    with pytest.raises(InvocationNotFound):
        store.attach_manifest("nope", "{}")
