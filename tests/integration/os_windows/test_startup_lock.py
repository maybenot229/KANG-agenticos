"""FileStartupLock against a real OS-level file lock (ADR-008 Part A2).

First occupant of `tests/integration/os_windows/` — 17_PROJECT_STRUCTURE
names this directory alongside sqlite/eventlog/obsidian/providers as "per
real technology," and until this ADR nothing in `os_windows/` had a real
OS-level mechanism to prove against (the tray, notifications port, and
credential manager it also names are either shell-side or unbuilt).
"""

from __future__ import annotations

import pytest

from kang.adapters.os_windows.startup_lock import FileStartupLock
from tests.fixtures.startup_lock_contract import StartupLockContract


class TestFileStartupLock(StartupLockContract):
    @pytest.fixture
    def make_lock(self, tmp_path):
        path = tmp_path / "core.lock"

        def factory():
            return FileStartupLock(path)

        return factory

    def test_the_lock_file_names_the_holding_process(self, tmp_path):
        # Windows file locking is mandatory, not advisory: a second handle
        # can't even read the byte-range `msvcrt.locking()` holds, so the
        # content is checked after release, not while held — the claim is
        # "the pid was persisted," not "readable by someone else mid-hold"
        # (which the exclusivity tests above already prove is impossible).
        import os

        path = tmp_path / "core.lock"
        lock = FileStartupLock(path)
        lock.acquire()
        assert path.exists()
        lock.release()
        assert path.read_bytes() == str(os.getpid()).encode("ascii")

    def test_acquire_survives_a_pre_existing_empty_file(self, tmp_path):
        # A leftover zero-byte file (e.g. from an earlier crash before
        # this ADR's write ever ran) must not be mistaken for a held
        # lock — only the OS-level lock, never the file's mere existence,
        # is the exclusion mechanism.
        path = tmp_path / "core.lock"
        path.touch()
        lock = FileStartupLock(path)
        lock.acquire()  # must not raise
        lock.release()
