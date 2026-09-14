"""FakeCredentialStore against the port contract (13 §2.3 fake/real pairing)."""

from __future__ import annotations

import pytest

from kang.adapters.fakes.credentials import FakeCredentialStore
from tests.fixtures.credential_store_contract import CredentialStoreContract


class TestFakeCredentialStore(CredentialStoreContract):
    @pytest.fixture
    def store(self):
        return FakeCredentialStore()

    @pytest.fixture
    def seed(self, store):
        return store.put
