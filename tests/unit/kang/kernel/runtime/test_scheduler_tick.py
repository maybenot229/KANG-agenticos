"""ADR-019 — the live scheduler tick loop's own trigger mechanism:
`service_actions()` on the composition root's `HTTPServer` subclass, gated
by TICK_INTERVAL_S via the injected Clock (never wall time directly — 11
§25 bans wall-clock outside ports). Proves the gating logic in isolation,
without a real Scheduler or a real serve_forever loop — those are proven
elsewhere (test_scheduler.py's tick() tests; the ADR's own live-verification
pass).

ADR-023: `_make_ticking_server_class`/`TICK_INTERVAL_S` moved to
`scheduler_wiring.py` when a third scheduled job pushed `composition.py`
past the size lint's hard limits — same composition-root role, split file.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler

from kang.kernel.runtime.scheduler_wiring import (
    TICK_INTERVAL_S,
    _make_ticking_server_class,
)

ANCHOR = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _MovableClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def set(self, now: datetime) -> None:
        self._now = now


class _RecordingScheduler:
    def __init__(self) -> None:
        self.ticks = 0

    def tick(self) -> None:
        self.ticks += 1


def _server(scheduler, clock):
    # BaseHTTPRequestHandler is a placeholder — service_actions() never
    # dispatches a request, so no real handler behavior is exercised.
    server_class = _make_ticking_server_class(scheduler, clock)
    return server_class(("127.0.0.1", 0), BaseHTTPRequestHandler)


def test_first_service_actions_call_ticks_immediately():
    scheduler = _RecordingScheduler()
    server = _server(scheduler, _MovableClock(ANCHOR))
    try:
        server.service_actions()
        assert scheduler.ticks == 1
    finally:
        server.server_close()


def test_within_interval_does_not_tick_again():
    scheduler = _RecordingScheduler()
    clock = _MovableClock(ANCHOR)
    server = _server(scheduler, clock)
    try:
        server.service_actions()
        clock.set(ANCHOR + timedelta(seconds=TICK_INTERVAL_S - 1))
        server.service_actions()
        assert scheduler.ticks == 1
    finally:
        server.server_close()


def test_after_interval_ticks_again():
    scheduler = _RecordingScheduler()
    clock = _MovableClock(ANCHOR)
    server = _server(scheduler, clock)
    try:
        server.service_actions()
        clock.set(ANCHOR + timedelta(seconds=TICK_INTERVAL_S))
        server.service_actions()
        assert scheduler.ticks == 2
    finally:
        server.server_close()


def test_no_scheduler_configured_never_ticks_and_never_raises():
    # core.scheduler is None when kang.toml is missing/invalid
    # (_wire_scheduler's fail-closed path) — service_actions() must be a
    # silent no-op, same as every other scheduler operation already is.
    server = _server(None, _MovableClock(ANCHOR))
    try:
        server.service_actions()
        server.service_actions()
    finally:
        server.server_close()
