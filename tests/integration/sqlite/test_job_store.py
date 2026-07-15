"""SqliteJobStore + SqliteKillSwitch against the contracts + persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.job_store import SqliteJobStore, SqliteKillSwitch
from kang.adapters.sqlite.migrations import apply_migrations
from tests.fixtures.job_store_contract import JobStoreContract, _job

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"


class TestSqliteJobStore(JobStoreContract):
    @pytest.fixture
    def conn(self, tmp_path):
        connection = open_connection(tmp_path / "kang.db")
        apply_migrations(connection, MIGRATIONS_DIR, FakeClock())
        yield connection
        connection.close()

    @pytest.fixture
    def store(self, conn) -> SqliteJobStore:
        return SqliteJobStore(conn, FakeClock())

    def test_runs_survive_reopen(self, tmp_path):
        first = open_connection(tmp_path / "kang.db")
        apply_migrations(first, MIGRATIONS_DIR, FakeClock())
        store = SqliteJobStore(first, FakeClock())
        store.register_job(_job("job-1"))
        run = store.start_run("job-1", _job().created_at, "c")
        store.finish_run(run, "ok", None)
        first.close()
        second = open_connection(tmp_path / "kang.db")
        assert SqliteJobStore(second, FakeClock()).last_slot("job-1") is not None
        second.close()


def _kill_switch(tmp_path):
    conn = open_connection(tmp_path / "kang.db")
    apply_migrations(conn, MIGRATIONS_DIR, FakeClock())
    return conn, SqliteKillSwitch(conn, FakeClock())


def test_kill_switch_defaults_disengaged(tmp_path):
    conn, switch = _kill_switch(tmp_path)
    assert not switch.is_engaged()
    conn.close()


def test_kill_switch_persists_across_reopen(tmp_path):
    conn, switch = _kill_switch(tmp_path)
    switch.engage("Kang pulled it")
    conn.close()
    reopened = open_connection(tmp_path / "kang.db")
    assert SqliteKillSwitch(reopened, FakeClock()).is_engaged()  # survived restart
    reopened.close()
