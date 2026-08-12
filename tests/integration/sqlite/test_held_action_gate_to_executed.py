"""ADR-021 — the full pipeline, real `Dispatcher`, real SQLite: `job.disable`
gates → `held_action.approve` drives the effect → the job is genuinely
disabled. Everything the fake-store handler tests and the transactional-
effect tests each prove in isolation, proven together through the actual
registered operations and the actual dispatch pipeline (scope check,
idempotency-key requirement, invocation/audit recording) — the closest
thing to a live run this suite can do without a real subprocess.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from kang.adapters.fakes.api_stores import (
    FakeIdempotencyStore,
    FakeInvocationStore,
    FakeSessionStore,
)
from kang.adapters.fakes.audit_log import FakeAuditLog
from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.held_action_store import SqliteHeldActionStore
from kang.adapters.sqlite.job_store import SqliteJobStore
from kang.adapters.sqlite.migrations import apply_migrations
from kang.api.dispatch import ApiRequest, Dispatcher, DispatcherDeps
from kang.api.operations import (
    ConfirmationDeps,
    make_held_action_approve_handler,
    make_job_disable_handler,
    make_job_enable_handler,
)
from kang.domain.ports.scheduler import Job
from kang.domain.ports.session import Session
from kang.kernel.audit.service import AuditService
from kang.kernel.permissions.engine import PermissionEngine

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"
VALID_TOKEN = "tok-kang"


@pytest.fixture
def rig(tmp_path):
    conn = open_connection(tmp_path / "kang.db")
    clock = FakeClock()
    apply_migrations(conn, MIGRATIONS_DIR, clock)
    held_actions = SqliteHeldActionStore(conn)
    job_store = SqliteJobStore(conn, clock)
    job_store.register_job(
        Job(
            id="deadline_sweep",
            name="deadline_sweep",
            schedule="hourly",
            catch_up="run_once_latest",
            created_at=clock.now(),
        )
    )
    ids = (f"id-{n}" for n in itertools.count())
    new_id = lambda: next(ids)  # noqa: E731

    transactional_effects = {
        "job.disable": lambda params: job_store.set_enabled_in_txn(
            params["job_id"], False
        ),
        "job.enable": lambda params: job_store.set_enabled_in_txn(
            params["job_id"], True
        ),
    }
    confirmation = ConfirmationDeps(
        held_actions=held_actions, clock=clock, new_id=new_id
    )
    handlers = {
        "job.disable": make_job_disable_handler(job_store, confirmation),
        "job.enable": make_job_enable_handler(job_store, confirmation),
        "held_action.approve": make_held_action_approve_handler(
            held_actions, clock, conn, transactional_effects
        ),
    }
    sessions = FakeSessionStore()
    sessions.create(
        Session(token=VALID_TOKEN, principal="kang", first_party=True, created_at="t")
    )
    dispatcher = Dispatcher(
        handlers,
        DispatcherDeps(
            sessions=sessions,
            permissions=PermissionEngine({"kang": ("*",)}),
            idempotency=FakeIdempotencyStore(),
            invocations=FakeInvocationStore(),
            audit=AuditService(FakeAuditLog(), clock),
            clock=clock,
            new_id=new_id,
        ),
    )
    return {
        "dispatcher": dispatcher,
        "job_store": job_store,
        "conn": conn,
        "sessions": sessions,
    }


def _request(operation, params, idempotency_key):
    return ApiRequest(
        operation=operation,
        params=params,
        session_token=VALID_TOKEN,
        idempotency_key=idempotency_key,
    )


def test_the_full_gate_to_executed_pipeline_disables_the_job(rig):
    dispatcher = rig["dispatcher"]

    gate = dispatcher.dispatch(
        _request(
            "job.disable",
            {"job_id": "deadline_sweep", "reason": "testing ADR-021"},
            "idem-1",
        )
    )
    assert gate["ok"] is False
    assert gate["error"]["code"] == "confirmation_required"
    held_id = gate["error"]["details"]["id"]
    assert rig["job_store"].list_jobs()[0].enabled is True  # untouched so far

    approval = dispatcher.dispatch(
        _request("held_action.approve", {"id": held_id}, "idem-2")
    )
    assert approval == {
        "ok": True,
        "result": {"id": held_id, "status": "executed"},
        "correlation_id": approval["correlation_id"],
    }
    assert rig["job_store"].list_jobs()[0].enabled is False


def test_re_enabling_after_disable_round_trips(rig):
    dispatcher = rig["dispatcher"]
    gate = dispatcher.dispatch(
        _request("job.disable", {"job_id": "deadline_sweep", "reason": "r"}, "idem-1")
    )
    dispatcher.dispatch(
        _request(
            "held_action.approve", {"id": gate["error"]["details"]["id"]}, "idem-2"
        )
    )
    assert rig["job_store"].list_jobs()[0].enabled is False

    gate2 = dispatcher.dispatch(
        _request("job.enable", {"job_id": "deadline_sweep", "reason": "r"}, "idem-3")
    )
    dispatcher.dispatch(
        _request(
            "held_action.approve", {"id": gate2["error"]["details"]["id"]}, "idem-4"
        )
    )
    assert rig["job_store"].list_jobs()[0].enabled is True


def test_a_plugin_session_without_jobs_write_is_denied_at_the_gate(rig):
    dispatcher = rig["dispatcher"]
    rig["sessions"].create(
        Session(
            token="tok-plugin",
            principal="plugin:scout",
            first_party=False,
            created_at="t",
        )
    )
    response = dispatcher.dispatch(
        ApiRequest(
            operation="job.disable",
            params={"job_id": "deadline_sweep", "reason": "r"},
            session_token="tok-plugin",
            idempotency_key="idem-1",
        )
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "permission_denied"
