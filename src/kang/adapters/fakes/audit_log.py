"""FakeAuditLog — in-memory AuditLog, contract-paired with JsonlAuditLog.

Layer: adapters/fakes (13 §2.3: the same contract suite runs against this
and the real adapter; divergence is a red build).
Constitutional home: 11_CODING §5/§7 (every port has an in-memory fake).
"""

from __future__ import annotations

from typing import Iterator

from kang.domain.ports.audit import (
    GENESIS_HASH,
    AuditEntry,
    AuditRecord,
    ChainVerification,
    compute_entry_hash,
)

__all__ = ["FakeAuditLog"]


class FakeAuditLog:
    """AuditLog over per-month lists. Append-only by construction."""

    def __init__(self) -> None:
        self._months: dict[str, list[AuditRecord]] = {}

    def append(self, entry: AuditEntry) -> AuditRecord:
        month = entry.at[:7]
        prev_hash = self.chain_head(month)
        record = AuditRecord(
            entry=entry,
            prev_hash=prev_hash,
            entry_hash=compute_entry_hash(prev_hash, entry),
        )
        self._months.setdefault(month, []).append(record)
        return record

    def records(self, month: str) -> Iterator[AuditRecord]:
        yield from self._months.get(month, [])

    def months(self) -> list[str]:
        return sorted(self._months)

    def verify(self, month: str) -> ChainVerification:
        prev_hash = GENESIS_HASH
        count = 0
        for index, record in enumerate(self.records(month)):
            expected = compute_entry_hash(prev_hash, record.entry)
            if record.prev_hash != prev_hash or record.entry_hash != expected:
                return ChainVerification(
                    intact=False, records=index + 1, broken_at=index
                )
            prev_hash = record.entry_hash
            count += 1
        return ChainVerification(intact=True, records=count)

    def chain_head(self, month: str) -> str:
        records = self._months.get(month)
        return records[-1].entry_hash if records else GENESIS_HASH
