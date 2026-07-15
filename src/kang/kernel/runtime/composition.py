"""Composition root — the ONE place concretions meet interfaces (17 §4.3).

Layer: kernel/runtime, but exempt from the import matrix: this is the single
module that MAY import adapters and the api, because something must
instantiate concretions and inject them (17 §4.3 composition-root
exception). It contains wiring only — no branching beyond config, no domain
logic. The exemption is registered by name in tools/importlinter.toml and
MUST NOT spread.

Constitutional home: 11_CODING §11 (composition root, plain constructor
calls, readable top to bottom), 17 §4.3, 12_API §5 (it assembles the
request pipeline), 07 F8 (fail-closed to Kang-only grants if permissions.toml
is missing/invalid).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from kang.adapters.config.permissions_loader import (
    KANG_ONLY_GRANTS,
    GrantLoadError,
    load_grants,
)
from kang.adapters.eventlog.delivery_store import SqliteDeliveryStore
from kang.adapters.eventlog.event_log import SqliteEventLog
from kang.adapters.eventlog.schema import open_eventlog
from kang.adapters.jsonl.audit_log import JsonlAuditLog
from kang.adapters.os_windows.clock import SystemClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.idempotency_store import SqliteIdempotencyStore
from kang.adapters.sqlite.invocation_store import SqliteInvocationStore
from kang.adapters.sqlite.migrations import apply_migrations
from kang.adapters.sqlite.recovery import SqliteRecoveryApplier
from kang.adapters.sqlite.session_store import SqliteSessionStore
from kang.adapters.sqlite.task_store import SqliteTaskStore
from kang.api.dispatch import Dispatcher, DispatcherDeps
from kang.api.http_binding import make_server
from kang.api.operations import (
    make_explain_invocation_handler,
    make_explain_stub_handler,
    make_registry_get_handler,
    make_task_create_handler,
    make_task_get_handler,
)
from kang.domain.ports.session import Session
from kang.kernel.audit.service import AuditService
from kang.kernel.bus.bus import EventBus
from kang.kernel.bus.delivery import Delivery
from kang.kernel.bus.reconciliation import Reconciliation
from kang.kernel.permissions.engine import build_checked_engine
from kang.kernel.runtime.ids import uuid7
from kang.kernel.runtime.sleeper import RealSleeper

__all__ = ["Core", "build_core", "serve"]

SESSION_FILE = "session.json"

MIGRATIONS_DIR = Path(__file__).resolve().parents[4] / "migrations"


@dataclass
class Core:
    """The wired system: the dispatcher plus what the server needs to mint a
    session and shut down cleanly."""

    dispatcher: Dispatcher
    sessions: SqliteSessionStore
    new_id: object
    _connections: list

    def mint_first_party_session(self) -> Session:
        token = self.new_id()  # type: ignore[operator]
        session = Session(
            token=token,
            principal="kang",
            first_party=True,
            created_at="",  # stamped below by the caller's clock if needed
        )
        self.sessions.create(session)
        return session

    def close(self) -> None:
        for connection in self._connections:
            connection.close()


def _load_grants(kang_home: Path):
    """Grant truth from %KANG_HOME%/config/permissions.toml; fail closed to
    Kang-only if absent or invalid (07 F8)."""
    try:
        return load_grants(kang_home / "config" / "permissions.toml")
    except (GrantLoadError, ValueError):
        return KANG_ONLY_GRANTS


def build_core(kang_home: Path, device_id: str = "device-local") -> Core:
    kang_home.mkdir(parents=True, exist_ok=True)
    clock = SystemClock()

    def new_id() -> str:
        return uuid7(int(clock.now().timestamp() * 1000), os.urandom)

    kang = open_connection(kang_home / "kang.db")
    apply_migrations(kang, MIGRATIONS_DIR, clock)
    events = open_eventlog(kang_home / "events" / "eventlog.db")

    audit = AuditService(JsonlAuditLog(kang_home / "audit"), clock)
    engine = build_checked_engine(_load_grants(kang_home))
    event_log = SqliteEventLog(events, clock)
    delivery = Delivery(
        event_log,
        SqliteDeliveryStore(events, clock),
        audit,
        dead_letter_id=new_id,
        sleeper=RealSleeper(),
    )
    reconciliation = Reconciliation(
        event_log, SqliteRecoveryApplier(kang), audit, clock
    )
    bus = EventBus(event_log, delivery, reconciliation, engine, audit)
    bus.recover()  # startup reconciliation + delivery resume (§4.4)

    task_store = SqliteTaskStore(kang, clock)
    invocations = SqliteInvocationStore(kang)
    handlers = {
        "registry.get": make_registry_get_handler(),
        "task.create": make_task_create_handler(
            bus, task_store, clock, new_id, device_id
        ),
        "task.get": make_task_get_handler(task_store),
        "explain.invocation": make_explain_invocation_handler(invocations, audit),
        "explain.plan_item": make_explain_stub_handler("plan item"),
        "explain.notification": make_explain_stub_handler("notification"),
        "explain.suggestion": make_explain_stub_handler("suggestion"),
        "explain.memory": make_explain_stub_handler("memory record"),
    }
    dispatcher = Dispatcher(
        handlers,
        DispatcherDeps(
            sessions=SqliteSessionStore(kang),
            permissions=engine,
            idempotency=SqliteIdempotencyStore(kang),
            invocations=invocations,
            audit=audit,
            clock=clock,
            new_id=new_id,
        ),
    )
    return Core(
        dispatcher=dispatcher,
        sessions=SqliteSessionStore(kang),
        new_id=new_id,
        _connections=[kang, events],
    )


def serve(kang_home: Path, host: str = "127.0.0.1", port: int = 0) -> None:
    """Wire the Core, mint a first-party session, write the session file the
    CLI reads (API-003: the Core's session file), and serve the operation
    channel until interrupted. port=0 binds an ephemeral port."""
    core = build_core(kang_home)
    session = core.mint_first_party_session()
    server = make_server(core.dispatcher, host, port)
    bound_host, bound_port = server.server_address[0], server.server_address[1]
    (kang_home / SESSION_FILE).write_text(
        json.dumps({"host": bound_host, "port": bound_port, "token": session.token}),
        encoding="utf-8",
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
        core.close()


if __name__ == "__main__":
    # python -m kang.kernel.runtime.composition <kang_home> [host] [port]
    home = Path(sys.argv[1])
    serve(
        home,
        host=sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1",
        port=int(sys.argv[3]) if len(sys.argv) > 3 else 0,
    )
