"""Idempotency port — a command's outcome is returned, not re-executed.

Layer: domain/ports. Ports own their datatypes (17 §7).
Constitutional home: 12_API API-004 (every command carries a
client-generated idempotency key; the Core returns the ORIGINAL outcome for
a repeated key rather than re-executing; 7-day retention). "Did my capture
save?" has a safe answer: resend and see.
"""

from __future__ import annotations

from typing import Protocol

__all__ = ["IdempotencyStore"]


class IdempotencyStore(Protocol):
    """Maps an idempotency key to the JSON of the command's first outcome."""

    def get(self, key: str) -> str | None:
        """The stored outcome JSON for this key, or None if unseen."""
        ...

    def put(self, key: str, outcome_json: str, at: str) -> None:
        """Record the first outcome for a key. A second put for the same key
        MUST NOT overwrite the first (the original outcome is authoritative)."""
        ...

    def purge_before(self, cutoff: str) -> int:
        """Drop keys recorded before `cutoff` (the 7-day retention sweep)."""
        ...
