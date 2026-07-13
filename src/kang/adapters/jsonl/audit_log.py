"""JsonlAuditLog — audit truth as monthly hash-chained JSONL files.

Layer: adapters/jsonl.
Constitutional home: 10_SECURITY SEC-013 (append-only JSONL, monthly-rotated
audit/YYYY-MM.jsonl, hash-chained per file; tamper-EVIDENT — an attacker
with full machine control can rewrite everything including chains, and the
chain claims nothing more); 07_DATABASE Part II (audit/ under %KANG_HOME%).

No update or delete exists in this module — absence is the append-only
guarantee's first line, the chain is its witness.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from kang.domain.ports.audit import (
    GENESIS_HASH,
    AuditEntry,
    AuditRecord,
    ChainVerification,
    compute_entry_hash,
)

__all__ = ["JsonlAuditLog"]


def _record_to_line(record: AuditRecord) -> str:
    return json.dumps(
        {
            "at": record.entry.at,
            "principal": record.entry.principal,
            "action": record.entry.action,
            "correlation_id": record.entry.correlation_id,
            "details": record.entry.details,
            "prev_hash": record.prev_hash,
            "hash": record.entry_hash,
        },
        sort_keys=True,
        ensure_ascii=False,
    )


def _line_to_record(line: str) -> AuditRecord:
    raw = json.loads(line)
    entry = AuditEntry(
        at=raw["at"],
        principal=raw["principal"],
        action=raw["action"],
        correlation_id=raw["correlation_id"],
        details=raw["details"],
    )
    return AuditRecord(entry=entry, prev_hash=raw["prev_hash"], entry_hash=raw["hash"])


class JsonlAuditLog:
    """AuditLog implementation over %KANG_HOME%/audit/YYYY-MM.jsonl."""

    def __init__(self, audit_dir: Path) -> None:
        self._dir = audit_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, month: str) -> Path:
        return self._dir / f"{month}.jsonl"

    def append(self, entry: AuditEntry) -> AuditRecord:
        month = entry.at[:7]  # YYYY-MM from the ISO timestamp
        prev_hash = self.chain_head(month)
        record = AuditRecord(
            entry=entry,
            prev_hash=prev_hash,
            entry_hash=compute_entry_hash(prev_hash, entry),
        )
        with self._path(month).open("a", encoding="utf-8") as sink:
            sink.write(_record_to_line(record) + "\n")
        return record

    def records(self, month: str) -> Iterator[AuditRecord]:
        path = self._path(month)
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as source:
            for line in source:
                if line.strip():
                    yield _line_to_record(line)

    def months(self) -> list[str]:
        return sorted(p.stem for p in self._dir.glob("*.jsonl"))

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
        head = GENESIS_HASH
        for record in self.records(month):
            head = record.entry_hash
        return head
