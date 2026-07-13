"""JsonlAuditLog against the port contract + file-level guarantees:
append-only JSONL on disk, bit-flip tamper detection (13 §2.9: "bit-flip a
record ⇒ chain verification fails loudly", SEC-013).
"""

from __future__ import annotations

import json

import pytest

from kang.adapters.jsonl.audit_log import JsonlAuditLog
from kang.domain.ports.audit import AuditEntry
from tests.fixtures.audit_log_contract import AuditLogContract, _entry


class TestJsonlAuditLog(AuditLogContract):
    @pytest.fixture
    def log(self, tmp_path) -> JsonlAuditLog:
        return JsonlAuditLog(tmp_path / "audit")

    # -- file-level guarantees -------------------------------------------

    def test_records_are_one_json_object_per_line(self, log, tmp_path):
        log.append(_entry(0))
        log.append(_entry(1))
        lines = (tmp_path / "audit" / "2026-01.jsonl").read_text().strip().splitlines()
        assert len(lines) == 2
        for line in lines:
            parsed = json.loads(line)
            assert {"at", "principal", "action", "prev_hash", "hash"} <= set(parsed)

    def test_bit_flip_breaks_the_chain_loudly(self, log, tmp_path):
        for index in range(3):
            log.append(_entry(index))
        path = tmp_path / "audit" / "2026-01.jsonl"
        lines = path.read_text().splitlines()
        lines[1] = lines[1].replace("task.create#1", "task.create#X")
        path.write_text("\n".join(lines) + "\n")
        verification = log.verify("2026-01")
        assert not verification.intact
        assert verification.broken_at == 1

    def test_deleting_a_record_breaks_the_chain_loudly(self, log, tmp_path):
        for index in range(3):
            log.append(_entry(index))
        path = tmp_path / "audit" / "2026-01.jsonl"
        lines = path.read_text().splitlines()
        path.write_text("\n".join([lines[0], lines[2]]) + "\n")
        verification = log.verify("2026-01")
        assert not verification.intact
        assert verification.broken_at == 1

    def test_reopening_the_log_continues_the_existing_chain(self, tmp_path):
        first_handle = JsonlAuditLog(tmp_path / "audit")
        first = first_handle.append(_entry(0))
        second_handle = JsonlAuditLog(tmp_path / "audit")
        second = second_handle.append(_entry(1))
        assert second.prev_hash == first.entry_hash
        assert second_handle.verify("2026-01").intact

    def test_details_may_be_absent(self, log):
        record = log.append(
            AuditEntry(
                at="2026-01-09T09:00:00+00:00",
                principal="kernel:scheduler",
                action="job.skipped",
                correlation_id=None,
                details=None,
            )
        )
        stored = list(log.records("2026-01"))[-1]
        assert stored == record
