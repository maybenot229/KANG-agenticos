"""ADR-019 — the live scheduler tick loop's own trigger mechanism, now a
native `asyncio` loop (ADR-036 D4) instead of an `HTTPServer.
service_actions()` override. Proves the gating logic in isolation,
without a real Scheduler or a real `serve()` — those are proven
elsewhere (`test_scheduler.py`'s `tick()` tests; the real-subprocess
replay suite's own boot-catch-up tests, unaffected by this change since
they exercise `catch_up()`, called before this loop ever starts).

ADR-023: this module moved to `scheduler_wiring.py` when a third
scheduled job pushed `composition.py` past the size lint's hard limits
— same composition-root role, split file.
"""

from __future__ import annotations

import asyncio

import kang.kernel.runtime.scheduler_wiring as scheduler_wiring_module
from kang.kernel.runtime.scheduler_wiring import _tick_forever, _tick_once


class _RecordingScheduler:
    def __init__(self) -> None:
        self.ticks = 0

    def tick(self) -> None:
        self.ticks += 1


class _FakeCore:
    def __init__(self, scheduler) -> None:
        self.scheduler = scheduler


class _RecordingWriteExecutor:
    """A stand-in that runs `fn` inline against a fixed core, exactly
    like the real `WriteExecutor.submit` does against its owned value —
    synchronous here since nothing in these tests needs real threading."""

    def __init__(self, core) -> None:
        self._core = core
        self.submissions = 0

    async def submit(self, fn):
        self.submissions += 1
        return fn(self._core)


def test_tick_once_ticks_when_a_scheduler_is_wired():
    scheduler = _RecordingScheduler()
    _tick_once(_FakeCore(scheduler))
    assert scheduler.ticks == 1


def test_tick_once_is_a_silent_noop_with_no_scheduler():
    # core.scheduler is None when kang.toml is missing/invalid
    # (_wire_scheduler's fail-closed path) — must be a silent no-op,
    # same as every other scheduler operation already is.
    _tick_once(_FakeCore(None))  # must not raise


def test_tick_forever_ticks_via_the_write_executor_repeatedly(monkeypatch):
    monkeypatch.setattr(scheduler_wiring_module, "TICK_INTERVAL_S", 0.01)
    scheduler = _RecordingScheduler()
    executor = _RecordingWriteExecutor(_FakeCore(scheduler))

    async def scenario():
        task = asyncio.ensure_future(_tick_forever(executor))
        await asyncio.sleep(0.05)  # several intervals at 0.01s each
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())
    # Several ticks in ~0.05s at a 0.01s interval — not exactly-once,
    # proving the loop genuinely repeats rather than firing a single time.
    assert executor.submissions >= 2
    assert scheduler.ticks == executor.submissions


def test_tick_forever_stops_cleanly_on_cancellation(monkeypatch):
    monkeypatch.setattr(scheduler_wiring_module, "TICK_INTERVAL_S", 0.01)
    executor = _RecordingWriteExecutor(_FakeCore(None))

    async def scenario():
        task = asyncio.ensure_future(_tick_forever(executor))
        await asyncio.sleep(0.02)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert task.cancelled()

    asyncio.run(scenario())
