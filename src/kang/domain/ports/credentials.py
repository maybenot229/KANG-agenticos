"""CredentialStore port — the ONE door to a raw secret (SEC-011, ADR-039).

Layer: domain/ports.
Constitutional home: 10_SECURITY SEC-011 ("raw secrets exist in exactly
one place (OS keychain) and transit exactly one component (adapter-
internal credential injection)... MUST NOT appear in: prompts,
manifests, logs, memory, config files, `plugin_kv`, exports, backups,
error messages, or the database"), §7 ("adapters request credentials by
*name* from the credential subsystem at call time; credentials live in
memory only for the duration of the call; no caching in any KANG
store... KANG detects auth failures and prompts, it never stores
fallback copies").
"""

from __future__ import annotations

from typing import Protocol

__all__ = ["CredentialNotFound", "CredentialStore"]


class CredentialNotFound(Exception):
    """No credential is stored under this name. The message carries the
    NAME only, never a value (SEC-011: a missing secret has none to
    leak, and this exception must not become the first place one
    accidentally does)."""


class CredentialStore(Protocol):
    """Request a secret by name, at call time, never cached (SEC-011).
    Deliberately `get`-only — no `set`/`delete` exists on this port at
    all (ADR-039 D2): rotation is explicitly Kang's own action ("in
    provider consoles + keychain update"), never KANG's. Implementations
    MUST NOT log, print, or persist the returned value anywhere but the
    caller's own immediate use."""

    def get(self, name: str) -> str:
        """Return the secret stored under `name`. Raises
        `CredentialNotFound` if absent — never a default, never a
        fallback value (SEC-011: "it never stores fallback copies")."""
        ...
