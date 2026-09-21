"""MemoryStore port-contract suite — run identically against the fake and the
real adapter (13 §2.3: divergence between fake and real is a red build).

Subclasses provide a `store` fixture (a fresh `MemoryStore`).
"""

from __future__ import annotations

from dataclasses import fields, replace

import pytest

from kang.domain.ports.memory_store import (
    MemoryConflict,
    MemoryRecord,
    content_fingerprint,
)


def record(**overrides) -> MemoryRecord:
    base = dict(
        id="mem-1",
        type="fact",
        status="active",
        content="School term ends June 12",
        trust_tier=2,
        confidence=1.0,
        sensitivity="normal",
        source_kind="stated",
        source_detail="conversation",
        reason="Kang said so",
        created_by="kang",
        created_at="2026-09-21T10:00:00+00:00",
        updated_at="2026-09-21T10:00:00+00:00",
        device_id="dev-1",
        revision=1,
    )
    base.update(overrides)
    return MemoryRecord(**base)


class MemoryStoreContract:
    def test_insert_then_get_round_trips_every_field(self, store):
        original = record(source_quote="term ends june 12", importance=0.7, pinned=True)
        store.insert_record(original)
        assert store.get("mem-1") == original

    def test_get_returns_none_for_an_unknown_id(self, store):
        assert store.get("never-saved") is None

    def test_a_duplicate_id_is_refused(self, store):
        store.insert_record(record())
        with pytest.raises(Exception):
            store.insert_record(record(content="different"))

    def test_no_returned_datatype_carries_a_rowid(self, store):
        store.insert_record(record())
        names = {f.name for f in fields(store.get("mem-1"))}
        assert not {n for n in names if "rowid" in n.lower()}

    def test_find_active_duplicate_matches_case_and_whitespace_folded_content(
        self, store
    ):
        store.insert_record(record())
        probe = content_fingerprint("  school   TERM ends june 12 ")
        assert store.find_active_duplicate("fact", probe) == "mem-1"

    def test_find_active_duplicate_is_scoped_to_the_type(self, store):
        store.insert_record(record())
        assert (
            store.find_active_duplicate("lesson", content_fingerprint(record().content))
            is None
        )

    def test_find_active_duplicate_ignores_non_active_records(self, store):
        store.insert_record(record(status="archived"))
        assert (
            store.find_active_duplicate("fact", content_fingerprint(record().content))
            is None
        )

    def test_find_active_duplicate_returns_none_when_nothing_matches(self, store):
        store.insert_record(record())
        assert store.find_active_duplicate("fact", content_fingerprint("other")) is None

    def test_merge_provenance_bumps_the_revision_and_keeps_the_content(self, store):
        store.insert_record(record())
        merged = replace(
            record(),
            source_detail="conversation\nagent:x observed:log",
            revision=2,
            updated_at="2026-09-21T11:00:00+00:00",
            device_id="dev-2",
        )
        store.merge_provenance(merged, expected_revision=1)
        stored = store.get("mem-1")
        assert stored == merged
        assert stored.content == record().content

    def test_merge_provenance_refuses_a_stale_revision(self, store):
        store.insert_record(record())
        with pytest.raises(MemoryConflict):
            store.merge_provenance(replace(record(), revision=6), expected_revision=5)

    def test_merge_provenance_refuses_an_unknown_record(self, store):
        with pytest.raises(MemoryConflict):
            store.merge_provenance(record(id="ghost", revision=2), expected_revision=1)
