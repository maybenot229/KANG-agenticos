"""KeyringCredentialStore — the OS keychain, wrapped (SEC-011, ADR-039).

Layer: adapters/os_windows (17_PROJECT_STRUCTURE's own listing for this
directory names "credential manager (SEC-011)").
Constitutional home: 10_SECURITY §7 (exactly one vault, Windows
Credential Manager; access by name at call time; never cached; Kang
sets/rotates credentials himself — KANG only ever reads).

Wraps `keyring` (ADR-039 D1's own E10 justification) rather than a raw
`ctypes`/`win32cred` binding: `keyring.get_password(service, username)`
IS this port's `get(name)` verbatim, already correctly handling the
Windows Credential Manager's actual binary credential-blob format —
hand-rolling that parsing for security-sensitive code is exactly the
"reinvents a solved problem" case this project already declined twice
(ADR-011, ADR-035) and now a third time. Verified empirically before
this file was written: `keyring.get_keyring()` resolves to
`WinVaultKeyring` on this machine; a real `set_password` →
`get_password` → `delete_password` round-trip against the actual
Windows Credential Manager succeeded and was cleaned up.

Every credential this system stores uses a FIXED username ("kang") —
SEC-011's own words, "every credential belongs to Kang": there is no
second user this system serves, so a per-credential username dimension
would be state with no meaning here. `keyring`'s own `(service,
username)` key shape needs a username regardless; this is its constant
value.
"""

from __future__ import annotations

import keyring

from kang.domain.ports.credentials import CredentialNotFound

__all__ = ["KeyringCredentialStore"]

_USERNAME = "kang"


class KeyringCredentialStore:
    """CredentialStore over the OS keychain via `keyring`. Kang sets and
    rotates each credential himself — via `keyring`'s own CLI (`keyring
    set <name> kang`, ships with the dependency, prompts securely) or
    the OS's native Credential Manager UI. This adapter never writes —
    `CredentialStore` has no `set`/`delete` method at all (ADR-039 D2)."""

    def get(self, name: str) -> str:
        value = keyring.get_password(name, _USERNAME)
        if value is None:
            raise CredentialNotFound(
                f"no credential named {name!r} in the OS keychain — "
                f"set it with: keyring set {name} {_USERNAME}"
            )
        return value
