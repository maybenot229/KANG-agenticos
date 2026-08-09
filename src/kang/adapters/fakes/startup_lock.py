"""FakeStartupLock — in-memory StartupLock, contract-paired (13 §2.3).

Layer: adapters/fakes.
Constitutional home: 11_CODING §5/§7 (every port has an in-memory fake).

Takes a shared `dict` rather than owning its own state, deliberately: the
whole point of a startup-lock test is two *separate* instances contending
for the *same* lock (mirroring two real OS processes racing for the same
file) — a fake that only tracked its own state could never reproduce that,
the one behavior this port exists to guarantee.
"""

from __future__ import annotations

from kang.domain.ports.startup_lock import AlreadyRunningError

__all__ = ["FakeStartupLock"]


class FakeStartupLock:
    """StartupLock over a dict shared across instances that name the same
    `key` — the fake's stand-in for "the same file on disk"."""

    def __init__(self, registry: dict, key: str = "default") -> None:
        self._registry = registry
        self._key = key
        self._held = False

    def acquire(self) -> None:
        if self._registry.get(self._key):
            raise AlreadyRunningError(
                f"another KANG Core already holds the startup lock {self._key!r}"
            )
        self._registry[self._key] = True
        self._held = True

    def release(self) -> None:
        if not self._held:
            return
        self._registry.pop(self._key, None)
        self._held = False
