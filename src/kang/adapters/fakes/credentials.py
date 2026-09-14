"""FakeCredentialStore — in-memory credentials for tests (13 §2.3).

Layer: adapters/fakes.
Constitutional home: 11_CODING §5/§7 (every port has an in-memory fake).
NEVER seeded with a real secret in any test — there is no reason a fake
would ever need one (13 §1: no network; nothing this fake feeds ever
reaches a real provider).
"""

from __future__ import annotations

from kang.domain.ports.credentials import CredentialNotFound

__all__ = ["FakeCredentialStore"]


class FakeCredentialStore:
    def __init__(self, secrets: dict[str, str] | None = None) -> None:
        self._secrets = dict(secrets or {})

    def get(self, name: str) -> str:
        try:
            return self._secrets[name]
        except KeyError:
            raise CredentialNotFound(f"no credential named {name!r}") from None

    def put(self, name: str, value: str) -> None:
        """Test-only convenience — NOT part of `CredentialStore` (the
        real port has no write method at all, ADR-039 D2). Lets tests
        seed this fake without reaching into a private attribute."""
        self._secrets[name] = value
