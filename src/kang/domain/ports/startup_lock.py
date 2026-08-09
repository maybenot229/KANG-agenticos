"""Startup lock port — ADR-008 Part A2: the core-side half of single-
instance enforcement.

Layer: domain/ports. Ports own their datatypes (17 §7).
Constitutional home: ADR-008 (`ui/shell/` already has A1, the shell-side
`tauri-plugin-single-instance`; this is A2, the core-side lock A1 cannot
substitute for — a core launched independently of the shell, e.g. by a
developer running it directly while the shell is also running, would
otherwise contend for `kang.db` and run a second scheduler/notifier/bus
against the same truth, a split-brain automation risk distinct from the
shell's own hotkey-collision crash). `04_ARCHITECTURE` D016 ("core starts
at login, lives in the tray") assumes exactly one resident core; this port
is what makes that assumption hold under a real second launch attempt
rather than an accident of nobody trying.

Exclusive, not advisory-by-convention: a second `acquire()` while the
first holder is alive MUST raise `AlreadyRunningError`, not merely log one.
Released automatically by the OS on process exit (even a crash) — the
concrete adapter's whole point is riding that guarantee rather than
re-implementing liveness detection (PID files, heartbeats) by hand.
"""

from __future__ import annotations

from typing import Protocol

__all__ = ["AlreadyRunningError", "StartupLock"]


class AlreadyRunningError(Exception):
    """Another live process already holds the startup lock."""


class StartupLock(Protocol):
    """One exclusive lock per `%KANG_HOME%`, held for the process's
    lifetime. Implementations: `FileStartupLock` (real, `adapters/
    os_windows/` — an OS-level file lock, released by the OS on process
    exit regardless of how it exits), `FakeStartupLock` (adapters/fakes —
    contract-tested against the real one, 13 §2.3)."""

    def acquire(self) -> None:
        """Take the lock. Raises AlreadyRunningError if another live
        process already holds it. Safe to call at most once per
        instance — a second `acquire()` on the same instance that already
        holds the lock is a caller defect, not a case this method
        handles."""
        ...

    def release(self) -> None:
        """Release the lock. Safe to call even if `acquire()` was never
        called or already failed — `Core.close()` calls this
        unconditionally during shutdown."""
        ...
