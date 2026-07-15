"""Checkpoint C4 — first working `kang explain` (18 §3 M4; 05 §14; 12 §12).

A REAL scenario, not a signature assertion: a task is created THROUGH the
CLI (a separate process, no core imports), then `explain.invocation`
reconstructs that invocation end-to-end from PERMANENT storage alone —
trigger → operation → outcome + the audit chain, keyed by correlation_id.

Persistence is proven by RESTARTING the Core between create and explain: a
fresh server process (no in-memory state from the first) reconstructs the
invocation from kang.db + audit/*.jsonl written by the previous process.
The reconstruction never touches the event log (12 §12 / 15 §8.3).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CLI = REPO_ROOT / "cli" / "kang_cli.py"
DEFAULT_PERMISSIONS = REPO_ROOT / "config" / "defaults" / "permissions.toml"


class _Server:
    """A Core server subprocess bound to an ephemeral local port."""

    def __init__(self, kang_home: Path) -> None:
        self._home = kang_home
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


def _cli(kang_home: Path, *args: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=str(REPO_ROOT),
        env={
            "KANG_HOME": str(kang_home),
            "PYTHONPATH": str(REPO_ROOT / "src"),
            "SystemRoot": _system_root(),
            "PATH": _path(),
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    # The CLI exits 0 on ok, 1 on a well-formed error envelope (both valid
    # responses); anything else (2, crash) is a real failure.
    assert result.returncode in (0, 1), f"CLI crashed: {result.stdout}\n{result.stderr}"
    return json.loads(result.stdout)


def _system_root() -> str:
    import os

    return os.environ.get("SystemRoot", "")


def _path() -> str:
    import os

    return os.environ.get("PATH", "")


@pytest.fixture
def kang_home(tmp_path):
    home = tmp_path / "kanghome"
    (home / "config").mkdir(parents=True)
    (home / "config" / "permissions.toml").write_text(
        DEFAULT_PERMISSIONS.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return home


def test_c4_task_creation_through_cli_is_explainable_after_restart(kang_home):
    # -- server A: create a task through the CLI --------------------------
    server_a = _Server(kang_home)
    server_a.wait_ready()
    try:
        created = _cli(kang_home, "task", "create", "prove the spine")
    finally:
        server_a.stop()

    assert created["ok"] is True
    correlation_id = created["correlation_id"]
    task_id = created["result"]["task_id"]
    assert task_id and correlation_id

    # -- server B: a FRESH process reconstructs from persistent storage ---
    server_b = _Server(kang_home)
    server_b.wait_ready()
    try:
        explained = _cli(kang_home, "explain", correlation_id)
        fetched = _cli(kang_home, "task", "get", task_id)
    finally:
        server_b.stop()

    # the invocation reconstructs end-to-end, from a process that never held
    # it in memory — persistence proven
    assert explained["ok"] is True
    result = explained["result"]
    assert result["correlation_id"] == correlation_id
    assert result["operation"] == "task.create"
    assert result["trigger"] == "cli"
    assert result["outcome"] == "ok"
    assert result["kind"] == "command"
    assert "invocation + audit" in result["reconstructed_from"]

    # the audit chain threads dispatched → ok under the one correlation_id
    actions = [entry["action"] for entry in result["chain"]]
    assert "task.create.dispatched" in actions
    assert "task.create.ok" in actions

    # and the task itself survived the restart (real committed truth)
    assert fetched["result"]["title"] == "prove the spine"
    assert fetched["result"]["status"] == "open"


def test_c4_explain_unknown_correlation_is_honest_not_found(kang_home):
    server = _Server(kang_home)
    server.wait_ready()
    try:
        explained = _cli(kang_home, "explain", "no-such-correlation")
    finally:
        server.stop()
    assert explained["ok"] is False
    assert explained["error"]["code"] == "not_found"
