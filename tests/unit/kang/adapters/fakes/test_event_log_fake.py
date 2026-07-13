"""FakeEventLog against the port contract (13 §2.3 fake/real pairing)."""

from __future__ import annotations

import pytest

from kang.adapters.fakes.event_log import FakeEventLog
from tests.fixtures.event_log_contract import EventLogContract


class TestFakeEventLog(EventLogContract):
    @pytest.fixture
    def log(self, clock) -> FakeEventLog:
        return FakeEventLog(clock)
