"""`serve()` enforces ADR-008 Part A2 for real: a second live Core against
the same %KANG_HOME% is rejected, not raced against.

Mirrors `test_boot_catchup.py`'s `_Server` subprocess shape for the same
reason that file gives — proving `FileStartupLock`'s own contract
(`tests/integration/os_windows/test_startup_lock.py`) works doesn't prove
`serve()` actually uses it as its first act, which is the real gap this
closes: two genuine `python -m kang.kernel.runtime.composition` processes,
same real KANG_HOME, second one must fail cleanly and the first must be
completely undisturbed.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from kang.adapters.sqlite.connection import open_connection

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULTS = REPO_ROOT / "config" / "defaults"


def _seed_config(kang_home: Path) -> None:
    config = kang_home / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "permissions.toml").write_text(
        (DEFAULTS / "permissions.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )


class _Server:
    """A real `serve()` subprocess bound to an ephemeral local port."""

    def __init__(self, kang_home: Path) -> None:
        self._session_file = kang_home / "session.json"
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

    def wait_exit(self, timeout: float = 20.0) -> tuple[int, str]:
        """For the SECOND server, which is expected to exit on its own —
        never writes session.json, so `wait_ready` would just time out."""
        try:
            code = self._proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            self._proc.kill()
            raise TimeoutError("second server never exited") from exc
        return code, self._proc.stderr.read().decode("utf-8")

    def stop(self) -> None:
        self._proc.terminate()
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait(timeout=10)


def test_a_second_real_core_against_the_same_home_is_rejected_cleanly(tmp_path):
    _seed_config(tmp_path)
    first = _Server(tmp_path)
    try:
        first.wait_ready()
        first_session = (tmp_path / "session.json").read_text(encoding="utf-8")

        second = _Server(tmp_path)
        exit_code, stderr = second.wait_exit()

        assert exit_code == 1
        assert "startup lock" in stderr.lower()
        # The first instance's own session handshake is completely
        # untouched — the second process never got far enough to
        # overwrite it (the lock is taken before anything else opens).
        assert (tmp_path / "session.json").read_text(encoding="utf-8") == first_session
    finally:
        first.stop()


def test_after_the_first_stops_a_new_core_can_start(tmp_path):
    _seed_config(tmp_path)
    first = _Server(tmp_path)
    first.wait_ready()
    first.stop()

    # The OS releases the lock the instant the first process exits — no
    # staleness window, no manual cleanup needed (FileStartupLock's own
    # whole reason for existing over a hand-rolled PID file).
    second = _Server(tmp_path)
    try:
        second.wait_ready()  # must not raise / must not be rejected
        conn = open_connection(tmp_path / "kang.db")
        conn.execute("SELECT 1").fetchone()  # the db is genuinely usable
        conn.close()
    finally:
        second.stop()
