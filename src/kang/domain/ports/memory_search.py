"""MemorySearchStore port — the lexical half of hybrid retrieval and batched
record hydration (ADR-056 D1).

Layer: domain/ports. Ports own their datatypes (17 §7).
Constitutional home: 06_MEMORY §5.2 (the `bm25_n` term; filters applied
before scoring), Part X (default vs deep search), 07_DATABASE §6.1 (FTS5
external-content tables; `private` rows are never indexed), Part XIV (the
hybrid candidate fetch budget), 11 §15 (no N+1 store calls — hydration is one
batched read).

The semantic half is `EmbeddingIndex.nearest_memory`; this port never sees a
vector.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from kang.domain.ports.memory_store import MemoryRecord

__all__ = ["LexicalHit", "MemorySearchStore"]


@dataclass(frozen=True)
class LexicalHit:
    record_id: str
    bm25: float  # FTS5 bm25(): more negative is a better match


class MemorySearchStore(Protocol):
    def lexical(
        self,
        query: str,
        statuses: Sequence[str],
        types: Sequence[str] | None,
        k: int,
    ) -> tuple[LexicalHit, ...]:
        """Up to `k` FTS hits for the words in `query` (any word may match —
        terms are OR-ed, so ranking, not filtering, rewards more of them),
        among non-`private` records whose status is in `statuses` and, when
        given, whose type is in `types`; best first. The query is words, never
        FTS syntax: operators and quotes in Kang's text are treated as text.
        A query with no words returns nothing."""
        ...

    def records(self, record_ids: Sequence[str]) -> tuple[MemoryRecord, ...]:
        """The rows for `record_ids` in one read; unknown ids are absent."""
        ...

    def standing(self, statuses: Sequence[str]) -> tuple[MemoryRecord, ...]:
        """ADR-058 D3's P1 candidates in one read: every non-`private`
        record whose status is in `statuses` and which is a `rule`, a
        `profile`, a `preference`, or pinned — ordered by id. Unscored:
        standing context is included by kind, not by relevance (06 Part
        XI)."""
        ...
