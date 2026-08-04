"""Registry -> TypeScript client generator, Python half (ADR-011).

Layer: tools (dev-only). Imports NOTHING from `kang.*` — same discipline
every other tools/ script already holds (17 §4.2: "tools: src imports at
runtime forbidden"), and the same reason `cli/kang_cli.py` never imports
the core either (17 §5: CLI speaks HTTP like every client, no core
imports). `registry.get`'s JSON is obtained the constitutionally correct
way per 12_API §1 ("every interface is a client of this contract and
nothing else"): boot a real, throwaway Core as a subprocess, call
`registry.get` through `cli/kang_cli.py` exactly as any client would, tear
the Core down. No new exception to the import ban was needed or taken.

Usage: python tools/generate_ts_client.py [output_json_path]
  Writes the registry's `registry.get` result (the served, JSON-safe
  form — schemas already resolved to JSON Schema, ADR-010 Ruling 3) to
  `output_json_path` (default: ui/registry.snapshot.json, a gitignored
  build artifact). The Node half (ui/scripts/generate-client.mjs) reads
  that file and emits TypeScript via json-schema-to-typescript.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSITION_MODULE = "kang.kernel.runtime.composition"
CLI_SCRIPT = REPO_ROOT / "cli" / "kang_cli.py"
DEFAULT_OUTPUT = REPO_ROOT / "ui" / "registry.snapshot.json"
BOOT_TIMEOUT_S = 15
POLL_INTERVAL_S = 0.1


class CoreBootTimeout(Exception):
    """The throwaway Core never wrote its session file in time."""


def _wait_for_session_file(kang_home: Path, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    session_file = kang_home / "session.json"
    while time.monotonic() < deadline:
        if session_file.exists():
            return
        time.sleep(POLL_INTERVAL_S)
    raise CoreBootTimeout(
        f"session.json never appeared under {kang_home} within {timeout_s}s"
    )


def fetch_registry_json() -> dict:
    """Boot a throwaway Core, call registry.get through the real CLI client,
    tear the Core down. Returns the parsed `result` (registry_snapshot()'s
    JSON-safe shape) — raises if the Core never came up or the call failed."""
    with tempfile.TemporaryDirectory(prefix="kang_ts_gen_") as tmp:
        kang_home = Path(tmp)
        core_proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                COMPOSITION_MODULE,
                str(kang_home),
                "127.0.0.1",
                "0",
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        try:
            _wait_for_session_file(kang_home, BOOT_TIMEOUT_S)
            cli_result = subprocess.run(
                [sys.executable, str(CLI_SCRIPT), "registry"],
                cwd=REPO_ROOT,
                env={**os.environ, "KANG_HOME": str(kang_home)},
                capture_output=True,
                text=True,
                timeout=10,
            )
        finally:
            core_proc.terminate()
            try:
                core_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                core_proc.kill()
                core_proc.wait(timeout=5)

        if cli_result.returncode != 0:
            raise RuntimeError(
                f"registry.get failed (exit {cli_result.returncode}): "
                f"{cli_result.stdout}\n{cli_result.stderr}"
            )
        envelope = json.loads(cli_result.stdout)
        if not envelope.get("ok"):
            raise RuntimeError(f"registry.get returned an error envelope: {envelope}")
        return envelope["result"]


def main(argv: list[str]) -> int:
    output_path = Path(argv[0]) if argv else DEFAULT_OUTPUT
    registry = fetch_registry_json()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(registry, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"wrote {output_path} ({len(registry['operations'])} operations)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
