"""ADR-021 — `held_action.approve`'s `transactional` commit_mode driver,
against a real SQLite connection.

The claim under test: the approve-flip, the target operation's own
effect, and mark-executed genuinely share ONE transaction — not just
that each step individually succeeds (the fakes-based
`test_held_action_operations.py` already can't prove this; there's no
real transaction to share). A forced failure mid-sequence must leave
BOTH the held action and the target row exactly as if nothing had been
attempted — the crash-safety promise ADR-001 Amendment made and this
ADR finally implements.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.held_action_store import SqliteHeldActionStore
from kang.adapters.sqlite.job_store import SqliteJobStore
from kang.adapters.sqlite.migrations import apply_migrations
from kang.api.dispatch import HandlerContext
from kang.api.errors import ApiError
from kang.api.operations.held_action_ops import make_held_action_approve_handler
from kang.domain.ports.held_action import HeldAction
from kang.domain.ports.scheduler import Job

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"
ANCHOR = datetime(2026, 1, 1, tzinfo=timezone.utc)
CONTEXT = HandlerContext(
    principal="kang", correlation_id="corr-1", trigger="cli", first_party=True
)


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
            created_at=ANCHOR,
        )
    )
    return {
        "conn": conn,
        "clock": clock,
        "held_actions": held_actions,
        "job_store": job_store,
    }


def _seed_pending(rig, *, operation: str = "job.disable") -> HeldAction:
    now = rig["clock"].now()
    held = HeldAction(
        id="held-0000",
        operation=operation,
        action="Disable job 'deadline_sweep'",
        principal="kang",
        reason="testing",
        reversibility="reversible — re-enable via job.enable",
        correlation_id="corr-origin",
        created_at=now.isoformat(),
        expires_at=(now + timedelta(hours=24)).isoformat(),
        params={"job_id": "deadline_sweep"},
    )
    rig["held_actions"].create(held)
    return held


def test_approve_drives_the_effect_to_executed_in_one_transaction(rig):
    _seed_pending(rig)
    effects = {
        "job.disable": lambda params: rig["job_store"].set_enabled_in_txn(
            params["job_id"], False
        )
    }
    handler = make_held_action_approve_handler(
        rig["held_actions"], rig["clock"], rig["conn"], effects
    )
    result = handler(CONTEXT, {"id": "held-0000"})
    assert result == {"id": "held-0000", "status": "executed"}
    assert rig["held_actions"].get("held-0000").status == "executed"
    assert rig["job_store"].list_jobs()[0].enabled is False


def test_a_failing_effect_rolls_back_both_the_flip_and_the_effect(rig):
    _seed_pending(rig)

    def _boom(params):
        raise RuntimeError("adapter exploded")

    handler = make_held_action_approve_handler(
        rig["held_actions"], rig["clock"], rig["conn"], {"job.disable": _boom}
    )
    with pytest.raises(RuntimeError):
        handler(CONTEXT, {"id": "held-0000"})
    # Neither write survived — indistinguishable from never having
    # attempted approval at all (ADR-001 Amendment's own promise).
    assert rig["held_actions"].get("held-0000").status == "pending"
    assert rig["job_store"].list_jobs()[0].enabled is True
    assert rig["conn"].in_transaction is False  # no transaction left dangling


def test_a_missing_effect_function_is_an_internal_error_not_a_silent_flip(rig):
    # commit_mode="transactional" but nothing registered in
    # TRANSACTIONAL_EFFECTS for this operation — a real wiring defect,
    # must surface loudly (SEC-005), never silently fall back to a bare
    # approve-flip that then has no way to ever reach `executed`.
    _seed_pending(rig, operation="job.disable")
    handler = make_held_action_approve_handler(
        rig["held_actions"], rig["clock"], rig["conn"], {}
    )
    with pytest.raises(ApiError) as exc:
        handler(CONTEXT, {"id": "held-0000"})
    assert exc.value.code == "internal"
    assert rig["held_actions"].get("held-0000").status == "pending"


def test_approving_an_expired_action_is_a_conflict_and_rolls_back(rig):
    now = rig["clock"].now()
    held = HeldAction(
        id="held-0000",
        operation="job.disable",
        action="Disable job 'deadline_sweep'",
        principal="kang",
        reason="testing",
        reversibility="reversible",
        correlation_id="corr-origin",
        created_at=now.isoformat(),
        expires_at=(now - timedelta(hours=1)).isoformat(),  # already expired
        params={"job_id": "deadline_sweep"},
    )
    rig["held_actions"].create(held)
    effects = {
        "job.disable": lambda params: rig["job_store"].set_enabled_in_txn(
            params["job_id"], False
        )
    }
    handler = make_held_action_approve_handler(
        rig["held_actions"], rig["clock"], rig["conn"], effects
    )
    with pytest.raises(ApiError) as exc:
        handler(CONTEXT, {"id": "held-0000"})
    assert exc.value.code == "conflict"
    assert rig["held_actions"].get("held-0000").status == "pending"
    assert rig["job_store"].list_jobs()[0].enabled is True
