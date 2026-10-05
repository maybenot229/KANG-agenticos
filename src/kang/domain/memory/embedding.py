"""The embedding worker's policy — one bounded pass (ADR-055 D7/D8).

Layer: domain (stdlib + domain/ports only — 11 §2). The provider call is an
injected callable (`Router.embed` at the composition root), the same shape
`CognitiveExecutorDeps.route` already uses, so this module never sees a
kernel or adapter type.

Constitutional home: 07_DATABASE §6.2 (vectors are built by the embedding
worker, batched, never by a trigger), DB-004 (versions are never mixed;
hot rows first; cutover only at full coverage), 06_MEMORY §12.1 (`private`
never embedded — the index never offers one), A9 (a missing provider is a
declared degraded state, not a crash), ADR-055 D6/D7/D8.

A vector is stored only into the version whose model produced it. During a
model migration `providers.toml` serves the NEW model, so the `active`
version is *unserved* until cutover — its new rows wait on FTS (DB-004's
per-row fallback) rather than receiving vectors from a different space. A
model that matches no version being filled is a mismatch: nothing is
stored, and the caller audits it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from kang.domain.ports.embedding_index import (
    EmbeddingIndex,
    EmbeddingVersion,
    PendingRecord,
    VectorWrite,
)
from kang.domain.ports.model_provider import (
    EmbeddingResult,
    NoProviderAvailable,
    ProviderUnavailable,
    TaskSpec,
)

__all__ = ["EMBED_BATCH_SIZE", "EmbedPassResult", "Embed", "run_embedding_pass"]

# ADR-055 D7: the most records one pass embeds. The pass runs on the single
# write executor (scheduled jobs do), so this bounds how long the writer is
# held: ~7 s at the spike's measured 1.24 chunks/s. A constant, not a
# memory.toml key — memory.toml fails closed for the gate (ADR-051 D8), and a
# new required key would brick an existing install's gate on upgrade.
EMBED_BATCH_SIZE = 8

Embed = Callable[[TaskSpec, tuple[str, ...]], EmbeddingResult]


@dataclass(frozen=True)
class EmbedPassResult:
    embedded: int
    skipped_stale: int  # read, embedded, but the row moved before the write
    cut_over: tuple[int, ...]  # versions that became active this pass
    unserved: tuple[int, ...]  # versions the configured model does not serve
    degraded: str | None  # "provider_unavailable" when no provider answered
    mismatch: str | None  # set when the served model/dimension fit no version


def run_embedding_pass(
    index: EmbeddingIndex, embed: Embed, batch_size: int = EMBED_BATCH_SIZE
) -> EmbedPassResult:
    """Fill each version (active first, then migrating) with at most
    `batch_size` records in total; cut a migrating version over once it is
    complete. Never raises for a missing provider — returns the degraded
    marker instead (A9)."""
    tally = _Tally()
    versions = index.versions_to_fill()
    served_models = {v.model for v in versions}
    for version in versions:
        if tally.budget(batch_size) > 0 and tally.mismatch is None:
            _fill(index, embed, version, served_models, tally, batch_size)
        if tally.degraded or tally.mismatch:
            break
        if (
            version.status == "migrating"
            and index.memory_coverage(version.ver).is_complete
        ):
            index.cut_over(version.ver)
            tally.cut_over.append(version.ver)
    return tally.result()


class _Tally:
    def __init__(self) -> None:
        self.read = 0
        self.embedded = 0
        self.skipped = 0
        self.cut_over: list[int] = []
        self.unserved: list[int] = []
        self.degraded: str | None = None
        self.mismatch: str | None = None

    def budget(self, batch_size: int) -> int:
        return batch_size - self.read

    def result(self) -> EmbedPassResult:
        return EmbedPassResult(
            embedded=self.embedded,
            skipped_stale=self.skipped,
            cut_over=tuple(self.cut_over),
            unserved=tuple(self.unserved),
            degraded=self.degraded,
            mismatch=self.mismatch,
        )


def _fill(
    index: EmbeddingIndex,
    embed: Embed,
    version: EmbeddingVersion,
    served_models: set[str],
    tally: _Tally,
    batch_size: int,
) -> None:
    pending = index.pending_memory(version.ver, tally.budget(batch_size))
    tally.read += len(pending)
    for sensitivity in sorted({p.sensitivity for p in pending}):
        group = tuple(p for p in pending if p.sensitivity == sensitivity)
        try:
            result = embed(_spec(group), tuple(p.content for p in group))
        except (NoProviderAvailable, ProviderUnavailable):
            tally.degraded = "provider_unavailable"
            return
        if result.model != version.model:
            if result.model in served_models:
                # The model is the same for every group, so this is the
                # first group: hand the whole read back to the budget.
                tally.unserved.append(version.ver)
                tally.read -= len(pending)
            else:
                tally.mismatch = (
                    f"provider served {result.model!r}; no embedding version "
                    f"being filled uses it (version {version.ver} is "
                    f"{version.model!r})"
                )
            return
        if any(len(vector) != version.dim for vector in result.vectors):
            tally.mismatch = (
                f"provider returned vectors not of dimension {version.dim} "
                f"for version {version.ver}"
            )
            return
        writes = tuple(VectorWrite(p, v) for p, v in zip(group, result.vectors))
        stored = index.store_memory_vectors(version.ver, writes)
        tally.embedded += stored
        tally.skipped += len(group) - stored


def _spec(group: tuple[PendingRecord, ...]) -> TaskSpec:
    # The record's own sensitivity is the privacy tier (D010): `private`
    # rows never reach here, so the Router's local-only filter is never what
    # keeps them safe — the index's selection is.
    return TaskSpec(
        task_class="embedding",
        privacy_tier=group[0].sensitivity,
        context_size=sum(len(p.content) // 4 + 1 for p in group),
        latency_tolerance="background",
    )
