"""AuditLog port-contract suite — run identically against FakeAuditLog and
JsonlAuditLog (13 §2.3). Subclasses provide a ``log`` fixture.
"""

from __future__ import annotations

from kang.domain.ports.audit import GENESIS_HASH, AuditEntry, compute_entry_hash


def _entry(index: int, month: str = "2026-01") -> AuditEntry:
    return AuditEntry(
        at=f"{month}-0{index + 1}T09:00:00+00:00",
        principal="kang",
        action=f"task.create#{index}",
        correlation_id=f"corr-{index:04d}",
        details={"index": index},
    )


class AuditLogContract:
    def test_first_record_chains_from_genesis(self, log):
        record = log.append(_entry(0))
        assert record.prev_hash == GENESIS_HASH
        assert record.entry_hash == compute_entry_hash(GENESIS_HASH, record.entry)

    def test_each_record_carries_the_previous_records_hash(self, log):
        first = log.append(_entry(0))
        second = log.append(_entry(1))
        assert second.prev_hash == first.entry_hash

    def test_records_round_trip_in_order(self, log):
        entries = [_entry(i) for i in range(3)]
        for entry in entries:
            log.append(entry)
        stored = [record.entry for record in log.records("2026-01")]
        assert stored == entries

    def test_chain_head_is_the_last_records_hash(self, log):
        log.append(_entry(0))
        last = log.append(_entry(1))
        assert log.chain_head("2026-01") == last.entry_hash

    def test_empty_month_has_genesis_head_and_intact_chain(self, log):
        assert log.chain_head("2031-12") == GENESIS_HASH
        verification = log.verify("2031-12")
        assert verification.intact and verification.records == 0

    def test_verify_reports_an_intact_chain(self, log):
        for index in range(5):
            log.append(_entry(index))
        verification = log.verify("2026-01")
        assert verification.intact
        assert verification.records == 5
        assert verification.broken_at is None

    def test_entries_rotate_into_monthly_files_by_timestamp(self, log):
        log.append(_entry(0, month="2026-01"))
        log.append(_entry(0, month="2026-02"))
        assert log.months() == ["2026-01", "2026-02"]
        assert len(list(log.records("2026-01"))) == 1
        assert len(list(log.records("2026-02"))) == 1

    def test_monthly_chains_are_independent(self, log):
        log.append(_entry(0, month="2026-01"))
        february_first = log.append(_entry(0, month="2026-02"))
        assert february_first.prev_hash == GENESIS_HASH
