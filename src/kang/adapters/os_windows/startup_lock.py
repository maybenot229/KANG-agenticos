"""FileStartupLock — the startup lock port over an OS-level file lock.

Layer: adapters/os_windows (OS-services adapter, per 17_PROJECT_STRUCTURE's
own listing for this directory — tray/notifications/credential manager,
now joined by this). Constitutional home: ADR-008 Part A2.

Uses `msvcrt.locking()` (stdlib, Windows-only — the reason this lives in
`os_windows/` and not a portable location, per NFR-010's "no Windows-only
CORE dependency": the core (kernel/domain) never imports this module
directly, only the composition root wires it behind the `StartupLock`
port, so NFR-010 is satisfied by the port boundary, not by this adapter
being portable itself). A POSIX equivalent (`fcntl.flock`) would be a
sibling adapter behind the same port, added when a POSIX build exists —
not needed today (D002: this is a Windows-first product).

Why a lock, not a PID file: a PID file needs its own liveness check
(is that PID still running, and is it still *this* process rather than a
reused PID?) — genuinely fiddly, cross-platform-inconsistent, and exactly
the kind of hand-rolled mechanism `msvcrt.locking()` exists to make
unnecessary. The OS releases the lock the instant the process exits, by
any means (clean shutdown, crash, `taskkill /F`) — no staleness window,
no second mechanism to keep correct.
"""

from __future__ import annotations

import msvcrt
import os
from pathlib import Path

from kang.domain.ports.startup_lock import AlreadyRunningError

__all__ = ["FileStartupLock"]

_LOCK_REGION_BYTES = 1


class FileStartupLock:
    """StartupLock backed by an exclusive, non-blocking `msvcrt.locking()`
    region on a file under `%KANG_HOME%`. The file's own content (this
    process's pid) is diagnostic only — the lock, not the content, is
    the exclusion mechanism; two processes racing to write the pid is
    harmless because only the lock-holder ever gets past `acquire()`."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._file = None

    def acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # 'a+b': create if missing, never truncates an existing file out
        # from under a holder that might (in a hypothetical future) still
        # be reading it — the lock call below is the real exclusion, this
        # mode choice is just being careful.
        handle = open(self._path, "a+b")
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, _LOCK_REGION_BYTES)
        except OSError as exc:
            handle.close()
            raise AlreadyRunningError(
                f"another KANG Core already holds the startup lock at {self._path}"
            ) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()).encode("ascii"))
        handle.flush()
        self._file = handle

    def release(self) -> None:
        if self._file is None:
            return
        try:
            self._file.seek(0)
            msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, _LOCK_REGION_BYTES)
        except OSError:
            pass  # already released (or never actually locked) — fine
        self._file.close()
        self._file = None
