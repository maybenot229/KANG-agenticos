"""The write-executor and read-pool DB-001 specifies (ADR-036 Slice 1/D3).

Layer: adapters/sqlite (the only home of SQL — DB-002; this module owns no
SQL itself, only the connections callers run SQL against).
Constitutional home: 07_DATABASE DB-001 — "exactly one write connection,
owned by a single async write-executor task; all writes flow through it
as queued, explicit transactions" + "a pool (default 4) of read-only
connections serves all reads."

Zero callers today, deliberately (ADR-036 D3: built and tested in
complete isolation so this slice can land without touching or risking
anything that exists). The scheduler's own tick task and the `aiohttp`
routing seam (ADR-036 D4, not yet built) are the first real callers.

**Why `ThreadPoolExecutor`, not a hand-rolled thread + queue.** `sqlite3`
connections default `check_same_thread=True` — a connection may only be
used from the thread that created it, forever. `asyncio.to_thread()`
dispatches onto a *shared*, general-purpose pool with no guarantee of
landing on the same worker twice (ADR-036's own Context finding — this
is exactly the trap that ruled bare `to_thread()` out for DB-001's single
write connection). A purpose-built, fixed-size `ThreadPoolExecutor` is
the same underlying mechanism `asyncio.to_thread()` itself uses
(`loop.run_in_executor`) — just with a dedicated pool instead of the
ambient shared one, so a connection opened by worker N is only ever
touched by worker N again.

**A deliberate simplification, named rather than silently accepted:**
connections are not explicitly closed on `stop()`/`aclose()` — they are
released when their owning worker thread exits (`ThreadPoolExecutor.
shutdown()` joins every thread; a thread's `threading.local` state, and
the connection it holds, is reclaimed with it). `ThreadPoolExecutor`
gives no way to address a specific worker for an explicit "close your
connection" job without risking one worker running it twice while
another runs it zero times. Acceptable for a single local process where
the whole interpreter exits together; revisit if this component is ever
used somewhere that isn't.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

__all__ = ["ReadPool", "WriteExecutor"]

T = TypeVar("T")

READ_POOL_SIZE = 4  # DB-001's own stated default


class WriteExecutor:
    """DB-001's single write connection, owned by one dedicated worker.

    `connect` is a factory, not a ready-made connection: the connection
    must be OPENED on the worker thread that will use it for its whole
    life, not opened elsewhere and handed over (that would violate
    `check_same_thread=True` on its very first real use).
    """

    def __init__(self, connect: Callable[[], object]) -> None:
        self._connect = connect
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="kang-write"
        )
        self._conn: object | None = None

    async def start(self) -> None:
        """Open the write connection, on the worker thread, before any
        work is submitted. Must be awaited exactly once before `submit`."""
        loop = asyncio.get_running_loop()
        self._conn = await loop.run_in_executor(self._executor, self._connect)

    async def submit(self, fn: Callable[[object], T]) -> T:
        """Run `fn(connection)` on the write worker; queued behind
        whatever was submitted before it (DB-001: "queued, explicit
        transactions") — `ThreadPoolExecutor`'s own internal work queue
        is FIFO for a single worker, so submission order is run order."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, fn, self._conn)

    async def stop(self) -> None:
        """Shut the worker down. See the module docstring's own note on
        why the connection itself is not explicitly closed here.

        `shutdown(wait=True)` blocks until the worker thread joins —
        genuinely blocking the event loop if awaited directly, so it is
        itself dispatched via `to_thread`-style `run_in_executor(None,
        ...)`. The shared default pool is fine here specifically: this
        one-off wait has no connection or thread-affinity requirement,
        unlike every other call in this module."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._executor.shutdown, True)


_read_local = threading.local()


def _open_worker_connection(connect: Callable[[], object]) -> None:
    """`ThreadPoolExecutor`'s `initializer` hook: runs once, on each
    worker thread, before that worker processes any submitted job — the
    one place a per-worker connection can be opened ON the thread that
    will own it for the pool's whole life."""
    _read_local.conn = connect()


def _run_against_worker_connection(fn: Callable[[object], T]) -> T:
    return fn(_read_local.conn)


class ReadPool:
    """DB-001's pool of read-only connections (default 4) — each worker
    opens and permanently owns exactly one, via `ThreadPoolExecutor`'s
    `initializer` hook, so submitting N calls concurrently genuinely uses
    up to N independent connections rather than serializing behind one.
    """

    def __init__(
        self, connect: Callable[[], object], size: int = READ_POOL_SIZE
    ) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=size,
            thread_name_prefix="kang-read",
            initializer=_open_worker_connection,
            initargs=(connect,),
        )

    async def submit(self, fn: Callable[[object], T]) -> T:
        """Run `fn(connection)` on whichever pool worker is free, against
        that worker's own permanently-owned connection."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor, _run_against_worker_connection, fn
        )

    async def stop(self) -> None:
        """See `WriteExecutor.stop`'s own note: this one-off wait has no
        connection/thread-affinity requirement, so it is fine to run on
        the shared default pool rather than this class's own workers."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._executor.shutdown, True)
