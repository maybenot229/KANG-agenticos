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
from kang.kernel.runtime.composition import MORNING_PLAN_JOB, build_core

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULTS = REPO_ROOT / "config" / "defaults"


def _seed_config(kang_home: Path) -> None:
    config = kang_home / "config"
    config.mkdir(parents=True, exist_ok=True)
    for name in ("permissions.toml", "kang.toml"):
        (config / name).write_text(
            (DEFAULTS / name).read_text(encoding="utf-8"), encoding="utf-8"
        )


def _register_job_then_backdate_it(kang_home: Path, days: int) -> None:
    """A freshly-registered job has no missed slots (its catch-up baseline
    is its own creation time) — boot once to register it, then backdate,
    mirroring `test_morning_plan_job.py::_simulate_downtime` exactly."""
    built = build_core(kang_home)
    built.close()
    conn = open_connection(kang_home / "kang.db")
    try:
        past = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        conn.execute(
            "UPDATE job SET created_at = ? WHERE id = ?", (past, MORNING_PLAN_JOB)
        )
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


def _job_run_count(kang_home: Path) -> int:
    conn = open_connection(kang_home / "kang.db")
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM job_run WHERE job_id = ?", (MORNING_PLAN_JOB,)
        ).fetchone()[0]
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
