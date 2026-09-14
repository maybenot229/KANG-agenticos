"""CredentialStore port-contract suite — run identically against the
fake and the real adapter (13 §2.3: divergence between fake and real is
itself a red build).

Subclasses provide a `store` fixture (a fresh `CredentialStore`) and a
`seed` fixture: a `(name, value) -> None` callable that puts a
credential in place before the test reads it, and is guaranteed to
clean up anything it seeded, real adapter included — never left behind
in the real Windows Credential Manager.

Every name this suite seeds carries a `kang-contract-test-` prefix,
deliberately, so a real run against the actual OS keychain (the
`KeyringCredentialStore` subclass) cannot collide with or overwrite a
credential Kang genuinely stores.
"""

from __future__ import annotations

import pytest

from kang.domain.ports.credentials import CredentialNotFound

_NAME = "kang-contract-test-credential-1"
_OTHER_NAME = "kang-contract-test-credential-2"
_NEVER_SEEDED = "kang-contract-test-never-seeded"


class CredentialStoreContract:
    def test_get_returns_the_seeded_value(self, store, seed):
        seed(_NAME, "sekrit-value")
        assert store.get(_NAME) == "sekrit-value"

    def test_get_raises_for_an_unseeded_name(self, store):
        with pytest.raises(CredentialNotFound):
            store.get(_NEVER_SEEDED)

    def test_the_not_found_message_never_contains_a_real_value(self, store, seed):
        seed(_OTHER_NAME, "super-secret-do-not-leak")
        try:
            store.get(_NEVER_SEEDED)
            raise AssertionError("expected CredentialNotFound")
        except CredentialNotFound as exc:
            assert "super-secret-do-not-leak" not in str(exc)
