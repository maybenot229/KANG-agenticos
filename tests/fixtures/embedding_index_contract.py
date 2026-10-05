"""EmbeddingIndex port-contract suite — run identically against the fake and
the real adapter (13 §2.3: divergence between fake and real is a red build;
ADR-055 D6).

Subclasses provide `memory` (a fresh MemoryStore), `index` (an
EmbeddingIndex over the same records) and `add_version` (a callable
`(ver, model, dim, status)` doing what a future migration would: register
the version and create its vector table).

The invalidation cases are the deletion covenant (06 §1.5: delete removes
"its embedding") and 06 Part III's vector-index edges, proven through the
store's own lifecycle methods — the real adapter loses the vector by
migration 0022's triggers, the fake by mirroring them.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from kang.adapters.fakes.model_provider import fake_vector
from kang.domain.ports.embedding_index import (
    EmbeddingIndexConflict,
    EmbeddingVersion,
    PendingRecord,
    VectorWrite,
)
from kang.domain.ports.memory_store import ContentEdit
from tests.fixtures.memory_store_contract import record

V1 = EmbeddingVersion(1, "nomic-embed-text", 768, "active")
NOW = "2026-10-05T10:00:00+00:00"


def _write(pending: PendingRecord, dim: int = 768) -> VectorWrite:
    return VectorWrite(pending, fake_vector(pending.content, dim))


def _embed_all(index, ver: int = 1, dim: int = 768) -> int:
    pending = index.pending_memory(ver, 1000)
    return index.store_memory_vectors(ver, [_write(p, dim) for p in pending])


def _seed(memory, count: int = 3) -> None:
    for i in range(count):
        memory.insert_record(
            record(
                id=f"mem-{i}",
                content=f"fact number {i} about the school term",
                updated_at=f"2026-09-2{i}T10:00:00+00:00",
            )
        )


class EmbeddingIndexContract:
    def test_version_one_is_the_only_version_to_fill(self, index):
        assert index.versions_to_fill() == (V1,)

    def test_pending_lists_embeddable_records_newest_first(self, memory, index):
        _seed(memory)
        pending = index.pending_memory(1, 10)
        assert [p.record_id for p in pending] == ["mem-2", "mem-1", "mem-0"]
        assert pending[0] == PendingRecord(
            "mem-2", "fact number 2 about the school term", 1, "normal"
        )

    def test_pending_honors_the_limit(self, memory, index):
        _seed(memory)
        assert len(index.pending_memory(1, 2)) == 2

    def test_private_archived_and_superseded_records_are_never_pending(
        self, memory, index
    ):
        memory.insert_record(
            record(
                id="p",
                content="[encrypted]",
                sensitivity="private",
                content_enc=b"ciphertext",
            )
        )
        memory.insert_record(record(id="a", content="old thing", status="archived"))
        memory.insert_record(record(id="s", content="older thing", status="superseded"))
        memory.insert_record(record(id="r", content="contested", status="under_review"))
        assert [p.record_id for p in index.pending_memory(1, 10)] == ["r"]

    def test_a_stored_vector_leaves_pending_and_counts_toward_coverage(
        self, memory, index
    ):
        _seed(memory)
        assert index.memory_coverage(1).embedded == 0
        assert _embed_all(index) == 3
        assert index.pending_memory(1, 10) == ()
        coverage = index.memory_coverage(1)
        assert (coverage.embedded, coverage.embeddable) == (3, 3)
        assert coverage.is_complete

    def test_a_write_for_a_record_edited_since_it_was_read_is_skipped(
        self, memory, index
    ):
        _seed(memory, 1)
        (pending,) = index.pending_memory(1, 10)
        memory.update_content(
            ContentEdit("mem-0", "edited", "fix", 1, "kang", "dev-1", NOW)
        )
        assert index.store_memory_vectors(1, [_write(pending)]) == 0
        assert index.memory_coverage(1).embedded == 0

    def test_a_write_for_a_record_archived_since_it_was_read_is_skipped(
        self, memory, index
    ):
        _seed(memory, 1)
        (pending,) = index.pending_memory(1, 10)
        memory.transition_status("mem-0", "active", "archived", "dev-1", NOW)
        stale = replace(pending, revision=2)  # even at the new revision
        assert index.store_memory_vectors(1, [_write(stale)]) == 0

    def test_editing_content_drops_the_vector(self, memory, index):
        _seed(memory, 1)
        _embed_all(index)
        memory.update_content(
            ContentEdit("mem-0", "a new assertion", "fix", 1, "kang", "dev-1", NOW)
        )
        assert [p.content for p in index.pending_memory(1, 10)] == ["a new assertion"]

    def test_archiving_drops_the_vector_and_restoring_does_not_resurrect_it(
        self, memory, index
    ):
        _seed(memory, 1)
        _embed_all(index)
        memory.transition_status("mem-0", "active", "archived", "dev-1", NOW)
        assert index.memory_coverage(1).embeddable == 0
        memory.transition_status("mem-0", "archived", "active", "dev-1", NOW)
        assert [p.record_id for p in index.pending_memory(1, 10)] == ["mem-0"]

    def test_moving_to_under_review_keeps_the_vector(self, memory, index):
        _seed(memory, 1)
        _embed_all(index)
        memory.transition_status("mem-0", "active", "under_review", "dev-1", NOW)
        assert index.memory_coverage(1).is_complete
        assert index.pending_memory(1, 10) == ()

    def test_pinning_keeps_the_vector(self, memory, index):
        _seed(memory, 1)
        _embed_all(index)
        memory.set_pinned("mem-0", True, "dev-1", NOW)
        assert index.pending_memory(1, 10) == ()

    def test_deleting_removes_the_vector(self, memory, index):
        _seed(memory, 2)
        _embed_all(index)
        memory.transition_status("mem-0", "active", "archived", "dev-1", NOW)
        memory.delete_and_tombstone_in_txn("mem-0", "kang", NOW)
        query = fake_vector("fact number 0 about the school term", 768)
        assert [n.record_id for n in index.nearest_memory(1, query, 5)] == ["mem-1"]

    def test_nearest_orders_by_cosine_distance(self, memory, index):
        _seed(memory)
        _embed_all(index)
        query = fake_vector("fact number 1 about the school term", 768)
        neighbors = index.nearest_memory(1, query, 2)
        assert neighbors[0].record_id == "mem-1"
        assert neighbors[0].distance == pytest.approx(0.0, abs=1e-5)
        assert len(neighbors) == 2
        assert neighbors[1].distance > neighbors[0].distance

    def test_cutover_refuses_a_version_that_is_not_migrating(self, index):
        with pytest.raises(EmbeddingIndexConflict):
            index.cut_over(1)

    def test_cutover_refuses_an_incomplete_migration(self, memory, index, add_version):
        _seed(memory)
        add_version(2, "next-model", 4, "migrating")
        pending = index.pending_memory(2, 1)
        index.store_memory_vectors(2, [_write(p, 4) for p in pending])
        with pytest.raises(EmbeddingIndexConflict):
            index.cut_over(2)

    def test_a_complete_migration_cuts_over_and_retires_the_old_space(
        self, memory, index, add_version
    ):
        _seed(memory)
        _embed_all(index)
        add_version(2, "next-model", 4, "migrating")
        assert [v.ver for v in index.versions_to_fill()] == [1, 2]
        _embed_all(index, ver=2, dim=4)
        index.cut_over(2)
        assert index.versions_to_fill() == (
            EmbeddingVersion(2, "next-model", 4, "active"),
        )
