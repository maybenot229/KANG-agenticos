"""StartupLock port-contract suite — run identically against the fake and
the real adapter (13 §2.3: divergence between fake and real is itself a
red build).

Subclasses provide a ``make_lock`` fixture: a zero-arg factory that
returns a fresh `StartupLock` instance bound to the SAME underlying lock
each call (the same file path for the real adapter, the same shared dict
key for the fake) — mirroring "two separate OS processes pointed at the
same %KANG_HOME%," the exact scenario ADR-008 Part A2 exists to guard.
"""

from __future__ import annotations

import pytest

from kang.domain.ports.startup_lock import AlreadyRunningError


class StartupLockContract:
    def test_acquire_then_release_allows_a_later_acquire(self, make_lock):
        first = make_lock()
        first.acquire()
        first.release()

        second = make_lock()
        second.acquire()  # must not raise — the lock was released
        second.release()

    def test_a_second_acquire_while_the_first_is_held_raises(self, make_lock):
        first = make_lock()
        first.acquire()
        try:
            second = make_lock()
            with pytest.raises(AlreadyRunningError):
                second.acquire()
        finally:
            first.release()

    def test_releasing_the_first_lets_a_pending_second_acquire_succeed(self, make_lock):
        first = make_lock()
        first.acquire()
        second = make_lock()
        with pytest.raises(AlreadyRunningError):
            second.acquire()

        first.release()
        second.acquire()  # must not raise now
        second.release()

    def test_release_is_safe_without_ever_acquiring(self, make_lock):
        lock = make_lock()
        lock.release()  # must not raise

    def test_release_is_safe_to_call_twice(self, make_lock):
        lock = make_lock()
        lock.acquire()
        lock.release()
        lock.release()  # must not raise
