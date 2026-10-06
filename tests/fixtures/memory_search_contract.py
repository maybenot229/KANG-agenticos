"""MemorySearchStore port-contract suite — fake and real (13 §2.3; ADR-056
D1). Subclasses provide `memory` (a fresh MemoryStore) and `search` (a
MemorySearchStore over the same records). Only behaviour both honour is
asserted here; stemming and FTS-syntax neutralisation are the real store's
own tests."""

from __future__ import annotations

from tests.fixtures.memory_store_contract import record

LIVE = ("active", "under_review")


def _seed(memory) -> None:
    memory.insert_record(record(id="a", content="robotics team meets on friday"))
    memory.insert_record(record(id="b", content="the robotics team mentor is Dr Lee"))
    memory.insert_record(record(id="c", content="school term ends in june"))
    memory.insert_record(
        record(id="d", content="robotics archive note", status="archived")
    )
    memory.insert_record(
        record(
            id="p",
            content="[encrypted]",
            sensitivity="private",
            content_enc=b"ciphertext",
        )
    )
    memory.insert_record(
        record(id="r", content="robotics budget", type="preference", trust_tier=1)
    )


class MemorySearchStoreContract:
    def test_matching_records_are_returned_best_first(self, memory, search):
        _seed(memory)
        hits = search.lexical("robotics mentor Lee", LIVE, None, 10)
        assert hits[0].record_id == "b"  # three words beat one
        assert {h.record_id for h in hits} == {"a", "b", "r"}

    def test_status_filter_controls_deep_search(self, memory, search):
        _seed(memory)
        live = {h.record_id for h in search.lexical("robotics", LIVE, None, 10)}
        deep = {
            h.record_id
            for h in search.lexical("robotics", (*LIVE, "archived"), None, 10)
        }
        assert "d" not in live and "d" in deep

    def test_private_records_are_never_found(self, memory, search):
        _seed(memory)
        assert search.lexical("encrypted", LIVE, None, 10) == ()

    def test_type_filter_and_limit(self, memory, search):
        _seed(memory)
        assert [
            h.record_id for h in search.lexical("robotics", LIVE, ["preference"], 10)
        ] == ["r"]
        assert len(search.lexical("robotics", LIVE, None, 2)) == 2
        assert search.lexical("robotics", LIVE, [], 10) == ()

    def test_a_query_without_words_finds_nothing(self, memory, search):
        _seed(memory)
        assert search.lexical("  ?! ", LIVE, None, 10) == ()

    def test_records_hydrates_in_one_read_and_skips_unknown_ids(self, memory, search):
        _seed(memory)
        rows = search.records(["c", "a", "nope"])
        assert [r.id for r in rows] == ["a", "c"]
        assert rows[0] == memory.get("a")
