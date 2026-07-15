"""FakeJobStore + FakeKillSwitch against the contracts (13 §2.3)."""

from __future__ import annotations

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.job_store import FakeJobStore, FakeKillSwitch
from tests.fixtures.job_store_contract import JobStoreContract


class TestFakeJobStore(JobStoreContract):
    @pytest.fixture
    def store(self) -> FakeJobStore:
        return FakeJobStore(clock=FakeClock())


def test_fake_kill_switch_engages_and_disengages():
    switch = FakeKillSwitch()
    assert not switch.is_engaged()
    switch.engage("halt")
    assert switch.is_engaged() and switch.reason == "halt"
    switch.disengage()
    assert not switch.is_engaged()
