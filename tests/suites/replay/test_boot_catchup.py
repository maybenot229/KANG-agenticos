"""`serve()` runs the scheduler's boot catch-up (composition.py::serve).

`Scheduler.catch_up()` itself is exhaustively proven correct already
(`test_morning_plan_job.py`, called directly against a `build_core()`
Core). What was NEVER proven — because nothing called it — is that the
real boot path (`serve()`, the function every real launch of KANG
actually runs) invokes it at all. This is a REAL subprocess test
(mirrors `test_c4_kang_explain.py`'s `_Server` shape) for exactly that
reason: a direct `build_core()` + `.catch_up()` call in-process would
prove `catch_up()` works, not that `serve()` remembers to call it —
the gap this test exists to close.
"""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.held_action_store import SqliteHeldActionStore
from kang.domain.ports.held_action import HeldAction
from kang.kernel.runtime.composition import build_core
from kang.kernel.runtime.scheduler_wiring import (
    DEADLINE_SWEEP_JOB,
    HELD_ACTION_EXPIRE_JOB,
    MORNING_PLAN_JOB,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULTS = REPO_ROOT / "config" / "defaults"


def _seed_config(kang_home: Path) -> None:
    config = kang_home / "config"
    config.mkdir(parents=True, exist_ok=True)
    for name in ("permissions.toml", "kang.toml"):
        (config / name).write_text(
            (DEFAULTS / name).read_text(encoding="utf-8"), encoding="utf-8"
        )


def _register_job_then_backdate_it(
    kang_home: Path, days: int = 0, hours: int = 0, job_id: str = MORNING_PLAN_JOB
) -> None:
    """A freshly-registered job has no missed slots (its catch-up baseline
    is its own creation time) — boot once to register it, then backdate,
    mirroring `test_morning_plan_job.py::_simulate_downtime` exactly."""
    built = build_core(kang_home)
    built.close()
    conn = open_connection(kang_home / "kang.db")
    try:
        past = (
            datetime.now(timezone.utc) - timedelta(days=days, hours=hours)
        ).isoformat()
        conn.execute("UPDATE job SET created_at = ? WHERE id = ?", (past, job_id))
        conn.commit()
    finally:
        conn.close()


class _Server:
    """A real `serve()` subprocess bound to an ephemeral local port."""

    def __init__(self, kang_home: Path) -> None:
        self._session_file = kang_home / "session.json"
        if self._session_file.exists():
            self._session_file.unlink()
        self._proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "kang.kernel.runtime.composition",
                str(kang_home),
                "127.0.0.1",
                "0",
            ],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def wait_ready(self, timeout: float = 20.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._session_file.exists():
                return
            if self._proc.poll() is not None:
                raise RuntimeError(self._proc.stderr.read().decode("utf-8"))
            time.sleep(0.05)
        raise TimeoutError("server did not write session.json in time")

    def stop(self) -> None:
        self._proc.terminate()
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait(timeout=10)


def _job_run_count(kang_home: Path, job_id: str = MORNING_PLAN_JOB) -> int:
    conn = open_connection(kang_home / "kang.db")
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM job_run WHERE job_id = ?", (job_id,)
        ).fetchone()[0]
    finally:
        conn.close()


def _job_run_outcome(kang_home: Path, job_id: str) -> str | None:
    conn = open_connection(kang_home / "kang.db")
    try:
        row = conn.execute(
            "SELECT outcome FROM job_run WHERE job_id = ?", (job_id,)
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def test_a_real_boot_catches_up_a_missed_morning(tmp_path):
    """The claim `serve()`'s own docstring now makes: boot catch-up runs
    before the operation channel accepts requests. Session.json only
    appears after `mint_first_party_session()`, which this session's
    `serve()` now calls AFTER `catch_up()` — so by the time this test's
    wait_ready() returns, the catch-up run (if any) already happened."""
    _seed_config(tmp_path)
    _register_job_then_backdate_it(tmp_path, days=3)
    assert _job_run_count(tmp_path) == 0  # nothing has run yet

    server = _Server(tmp_path)
    try:
        server.wait_ready()
        assert _job_run_count(tmp_path) == 1  # run_once_latest: exactly one
    finally:
        server.stop()


def test_a_real_boot_with_no_missed_slots_does_not_crash_or_double_run(tmp_path):
    """A freshly-registered job (no backdating) has nothing to catch up —
    boot must complete cleanly with zero runs, not error."""
    _seed_config(tmp_path)
    build_core(tmp_path).close()  # registers the job, nothing backdated
    assert _job_run_count(tmp_path) == 0

    server = _Server(tmp_path)
    try:
        server.wait_ready()
        assert _job_run_count(tmp_path) == 0
    finally:
        server.stop()


def test_deadline_sweep_is_registered_and_boot_catches_up_a_missed_hour(tmp_path):
    """ADR-020: deadline_sweep is a real second job, wired identically to
    morning_plan — backdated by an hour, a real boot must catch it up
    exactly once (run_once_latest), and it must actually succeed
    (outcome='ok'), proving the deadlines.mark_alerted grant this ADR
    added is really there, not just that a job_run row exists."""
    _seed_config(tmp_path)
    _register_job_then_backdate_it(tmp_path, hours=3, job_id=DEADLINE_SWEEP_JOB)
    assert _job_run_count(tmp_path, DEADLINE_SWEEP_JOB) == 0

    server = _Server(tmp_path)
    try:
        server.wait_ready()
        assert _job_run_count(tmp_path, DEADLINE_SWEEP_JOB) == 1
        assert _job_run_outcome(tmp_path, DEADLINE_SWEEP_JOB) == "ok"
        # morning_plan is unaffected — two independently catching-up jobs,
        # not one replacing the other.
        assert _job_run_count(tmp_path, MORNING_PLAN_JOB) == 0
    finally:
        server.stop()


def test_held_action_expire_is_registered_and_boot_catches_up_a_missed_day(tmp_path):
    """ADR-022: held_action_expire is a real third job, wired identically
    to morning_plan/deadline_sweep — backdated by 2 days, a real boot must
    catch it up exactly once (run_once_latest), it must actually succeed
    (outcome='ok'), AND a real pending-but-expired held action must
    genuinely transition to 'expired' (ADR-024 — was 'cancelled' before
    the terminal-state split) — not just that a job_run row exists, that
    the store write it drives actually happened."""
    _seed_config(tmp_path)
    _register_job_then_backdate_it(tmp_path, days=2, job_id=HELD_ACTION_EXPIRE_JOB)
    assert _job_run_count(tmp_path, HELD_ACTION_EXPIRE_JOB) == 0

    conn = open_connection(tmp_path / "kang.db")
    try:
        now = datetime.now(timezone.utc)
        held = HeldAction(
            id="held-boot-expiry-0000",
            operation="job.disable",
            action="Disable job 'deadline_sweep'",
            principal="kang",
            reason="proving the real sweep",
            reversibility="reversible — re-enable via job.enable",
            correlation_id="corr-origin",
            created_at=(now - timedelta(hours=25)).isoformat(),
            expires_at=(now - timedelta(hours=1)).isoformat(),  # already expired
            params={"job_id": "deadline_sweep"},
        )
        SqliteHeldActionStore(conn).create(held)
    finally:
        conn.close()

    server = _Server(tmp_path)
    try:
        server.wait_ready()
        assert _job_run_count(tmp_path, HELD_ACTION_EXPIRE_JOB) == 1
        assert _job_run_outcome(tmp_path, HELD_ACTION_EXPIRE_JOB) == "ok"
        # morning_plan/deadline_sweep are unaffected — three independently
        # catching-up jobs, not one replacing the others.
        assert _job_run_count(tmp_path, MORNING_PLAN_JOB) == 0
        assert _job_run_count(tmp_path, DEADLINE_SWEEP_JOB) == 0
    finally:
        server.stop()

    conn = open_connection(tmp_path / "kang.db")
    try:
        status = conn.execute(
            "SELECT status FROM held_action WHERE id = ?", (held.id,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert status == "expired"  # the real sweep genuinely expired it (ADR-024)


def test_a_real_boot_with_no_kang_toml_does_not_crash(tmp_path):
    """core.scheduler is None when kang.toml is missing/invalid
    (_wire_scheduler's own fail-closed path, 07 F8's shape) — serve()
    must still boot cleanly, automation off, not bricked (SEC-009)."""
    config = tmp_path / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "permissions.toml").write_text(
        (DEFAULTS / "permissions.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    # No kang.toml written — the fail-closed-to-no-automation path.

    server = _Server(tmp_path)
    try:
        server.wait_ready()  # must not raise / must not crash on boot
    finally:
        server.stop()
