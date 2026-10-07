"""FakeMemorySearchStore — in-memory MemorySearchStore, contract-paired
(13 §2.3; ADR-056 D1).

Layer: adapters/fakes. Reads records from a `FakeMemoryStore`. The real store
ranks with FTS5's bm25 over porter-stemmed tokens; this fake ranks by how
many distinct query words a record contains, case-folded, without stemming,
and reports that count negated as its "bm25" (more negative is better, as
FTS5 does). The shared contract asserts only what both honour: which records
match, the filters, the limit, and that more matched words rank higher.
"""

from __future__ import annotations

import re
from typing import Sequence

from kang.adapters.fakes.memory_store import FakeMemoryStore
from kang.domain.ports.memory_search import LexicalHit
from kang.domain.ports.memory_store import MemoryRecord

__all__ = ["FakeMemorySearchStore"]

_WORD = re.compile(r"\w+", re.UNICODE)


def _words(text: str) -> set[str]:
    return {w.casefold() for w in _WORD.findall(text)}


class FakeMemorySearchStore:
    def __init__(self, memory: FakeMemoryStore) -> None:
        self._memory = memory

    def lexical(
        self,
        query: str,
        statuses: Sequence[str],
        types: Sequence[str] | None,
        k: int,
    ) -> tuple[LexicalHit, ...]:
        wanted = _words(query)
        hits = []
        for r in self._memory.snapshot().values():
            if (
                r.status not in statuses
                or r.sensitivity == "private"
                or (types is not None and r.type not in types)
            ):
                continue
            matched = len(wanted & _words(r.content))
            if matched:
                hits.append(LexicalHit(r.id, -float(matched)))
        hits.sort(key=lambda h: (h.bm25, h.record_id))
        return tuple(hits[:k])

    def records(self, record_ids: Sequence[str]) -> tuple[MemoryRecord, ...]:
        snapshot = self._memory.snapshot()
        return tuple(snapshot[i] for i in sorted(set(record_ids)) if i in snapshot)

    def standing(self, statuses: Sequence[str]) -> tuple[MemoryRecord, ...]:
        return tuple(
            r
            for _, r in sorted(self._memory.snapshot().items())
            if r.status in statuses
            and r.sensitivity != "private"
            and (r.type in ("rule", "profile", "preference") or r.pinned)
        )
