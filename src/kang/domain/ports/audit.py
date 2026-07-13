"""Audit port — the shape and chain arithmetic of audit truth.

Layer: domain/ports. Ports own their datatypes and the pure canonical-form
functions on them (17 §7); the WRITER authority lives in kernel/audit (the
sole writer, SEC-013/S5), the file I/O in adapters.
Constitutional home: 10_SECURITY SEC-013 (append-only JSONL, monthly files,
hash-chained per file: each record carries the previous record's hash;
tamper-EVIDENT, honestly not tamper-proof); SEC-006 (every entry carries
principal, correlation id, timestamp).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterator, Protocol

__all__ = [
    "GENESIS_HASH",
    "AuditEntry",
    "AuditLog",
    "AuditRecord",
    "ChainVerification",
    "compute_entry_hash",
]

# First record of each monthly file chains from this explicit genesis marker.
GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class AuditEntry:
    """What an acting component states about its own action (SEC-006)."""

    at: str  # ISO-8601, from the injected clock
    principal: str
    action: str
    correlation_id: str | None
    details: dict[str, Any] | None = None


@dataclass(frozen=True)
class AuditRecord:
    """An entry as persisted: chained to its predecessor."""

    entry: AuditEntry
    prev_hash: str
    entry_hash: str


def _canonical(entry: AuditEntry) -> str:
    return json.dumps(
        {
            "at": entry.at,
            "principal": entry.principal,
            "action": entry.action,
            "correlation_id": entry.correlation_id,
            "details": entry.details,
        },
        sort_keys=True,
        ensure_ascii=False,
    )


def compute_entry_hash(prev_hash: str, entry: AuditEntry) -> str:
    """SEC-013 chain step: hash over (previous record's hash + canonical
    entry). Deterministic — same chain, same bytes, same digest."""
    return hashlib.sha256((prev_hash + _canonical(entry)).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ChainVerification:
    """Result of walking a chain. broken_at is the 0-based index of the
    first record whose hash does not verify (None = intact)."""

    intact: bool
    records: int
    broken_at: int | None = None


class AuditLog(Protocol):
    """Persistence port for audit truth. Append-only by contract: no
    update, no delete exists on this surface, ever."""

    def append(self, entry: AuditEntry) -> AuditRecord:
        """Persist the entry chained to the current head; return the record."""
        ...

    def records(self, month: str) -> Iterator[AuditRecord]:
        """All records of a month ('YYYY-MM'), oldest first."""
        ...

    def months(self) -> list[str]:
        """Months with audit records, ascending."""
        ...

    def verify(self, month: str) -> ChainVerification:
        """Recompute the month's chain; report the first break loudly."""
        ...

    def chain_head(self, month: str) -> str:
        """Hash of the month's last record (GENESIS_HASH when empty) — the
        value the daily backup manifest records (SEC-013)."""
        ...
