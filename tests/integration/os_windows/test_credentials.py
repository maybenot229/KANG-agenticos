"""KeyringCredentialStore against the port contract AND the real Windows
Credential Manager (ADR-039). Every credential this suite writes is
`kang-contract-test-`-prefixed (the contract's own discipline) and
deleted in the fixture's own teardown — never left behind in Kang's
real keychain.
"""

from __future__ import annotations

import keyring
import pytest

from kang.adapters.os_windows.credentials import _USERNAME, KeyringCredentialStore
from tests.fixtures.credential_store_contract import CredentialStoreContract


class TestKeyringCredentialStore(CredentialStoreContract):
    @pytest.fixture
    def store(self):
        return KeyringCredentialStore()

    @pytest.fixture
    def seed(self):
        written: list[str] = []

        def _seed(name: str, value: str) -> None:
            keyring.set_password(name, _USERNAME, value)
            written.append(name)

        yield _seed
        for name in written:
            keyring.delete_password(name, _USERNAME)

    def test_uses_the_real_windows_vault_keyring_backend(self):
        # Confirms this test actually exercises the OS keychain, not a
        # fallback in-memory backend keyring silently substitutes when
        # no real one is available (it has one, and that would make
        # every assertion above pass for the wrong reason).
        backend = type(keyring.get_keyring()).__name__
        assert "Windows" in backend or "WinVault" in backend
