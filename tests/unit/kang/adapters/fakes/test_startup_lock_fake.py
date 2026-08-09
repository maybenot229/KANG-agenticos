"""FakeStartupLock against the port contract (13 §2.3 fake/real pairing)."""

from __future__ import annotations

import pytest

from kang.adapters.fakes.startup_lock import FakeStartupLock
from tests.fixtures.startup_lock_contract import StartupLockContract


class TestFakeStartupLock(StartupLockContract):
    @pytest.fixture
    def make_lock(self):
        registry: dict = {}

        def factory():
            return FakeStartupLock(registry, key="kang-home")

        return factory
