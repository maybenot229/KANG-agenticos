"""KANG CLI — a thin client of the Core API contract (12_API §1; UI-P1).

Layer: cli/ — a peer of ui/, NOT part of src/kang/. It imports NOTHING from
the core (17 §4.2/§4.3 rule 10); it speaks the API's local HTTP binding like
every other client, over stdlib only. All truth and logic live in the Core;
this renders the contract's responses.

Session handshake (API-003): the Core writes %KANG_HOME%/session.json with
{host, port, token}; the CLI reads it and presents the token on every
request. `KANG_HOME` comes from the environment — the CLI resolves its own
env, never the core's config port.

Commands:
  kang_cli.py task create <title> [priority]   → task_id + correlation_id
  kang_cli.py task get <id>
  kang_cli.py explain <correlation_id>
  kang_cli.py registry
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
import uuid
from pathlib import Path
from typing import Any


def _session(kang_home: Path) -> dict[str, Any]:
    data = json.loads((kang_home / "session.json").read_text(encoding="utf-8"))
    return data


def _call(
    kang_home: Path, operation: str, params: dict, idempotency_key: str | None = None
) -> dict[str, Any]:
    session = _session(kang_home)
    body: dict[str, Any] = {"operation": operation, "params": params}
    if idempotency_key is not None:
        body["idempotency_key"] = idempotency_key
    request = urllib.request.Request(
        f"http://{session['host']}:{session['port']}/op",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Session-Token": session["token"],
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _print(result: dict[str, Any]) -> int:
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


def main(argv: list[str]) -> int:
    kang_home = Path(os.environ["KANG_HOME"])
    if not argv:
        print("usage: kang_cli.py <task|explain|registry> ...", file=sys.stderr)
        return 2
    command = argv[0]
    if command == "task" and len(argv) >= 3 and argv[1] == "create":
        params: dict[str, Any] = {"title": argv[2]}
        if len(argv) >= 4:
            params["priority"] = int(argv[3])
        return _print(_call(kang_home, "task.create", params, str(uuid.uuid4())))
    if command == "task" and len(argv) >= 3 and argv[1] == "get":
        return _print(_call(kang_home, "task.get", {"id": argv[2]}))
    if command == "explain" and len(argv) >= 2:
        return _print(
            _call(kang_home, "explain.invocation", {"correlation_id": argv[1]})
        )
    if command == "registry":
        return _print(_call(kang_home, "registry.get", {}))
    print(f"unknown command: {' '.join(argv)}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
