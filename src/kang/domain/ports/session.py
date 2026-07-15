"""Session port — local session → principal resolution (authentication).

Layer: domain/ports. Ports own their datatypes (17 §7).
Constitutional home: 12_API API-003 (authentication = local session
establishment: a token resolves to a principal; the API refuses requests
with no valid session and adds NO second authorization vocabulary —
authorization is entirely the Permission Engine's, D013). First-party
clients get an OS-user-bound token from the Core's session file; plugin
sessions are minted at enable-time bound to `plugin:{id}`.

This port answers only "who is this token?", never "may they?". The
resolved principal feeds the existing engine.check (M3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

__all__ = ["Session", "SessionInvalid", "SessionStore"]


@dataclass(frozen=True)
class Session:
    """A live local session (12 §4). `first_party` gates the operations that
    only Kang's own UI may perform (held_action.approve — 12 §7)."""

    token: str
    principal: str
    first_party: bool
    created_at: str


class SessionInvalid(Exception):
    """No live session for the presented token — the API refuses the request
    (API-003: the only thing the API layer authenticates)."""


class SessionStore(Protocol):
    """Mints and resolves local sessions."""

    def create(self, session: Session) -> None:
        """Register a session."""
        ...

    def resolve(self, token: str) -> Session:
        """Resolve a token to its Session, or raise SessionInvalid."""
        ...
