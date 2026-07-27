"""FakeNotificationStore against the same port contract as the real store."""

from __future__ import annotations

import pytest

from kang.adapters.fakes.notification_store import FakeNotificationStore
from tests.fixtures.notification_store_contract import NotificationStoreContract


class TestFakeNotificationStore(NotificationStoreContract):
    @pytest.fixture
    def store(self) -> FakeNotificationStore:
        return FakeNotificationStore()
