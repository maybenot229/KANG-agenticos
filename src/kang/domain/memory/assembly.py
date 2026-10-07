"""The Context Assembler's pure core — filters, budgeting, rendering and the
manifest (ADR-058 D3/D5/D6).

Layer: domain (stdlib + domain/ports only). No I/O and no clock: everything
the result depends on is a parameter, so the same inputs give byte-identical
output (05 AG-009; 13 §2.6). The kernel's `ContextAssembler` gathers the
inputs through ports and calls these functions.

Constitutional home: 06_MEMORY §5.4 (the manifest; the `[MEM:id]` block
format), Part XI (P0–P4, budget shares, unused budget cascades downward,
truncation bottom-up and always recorded), 05 AG-009 (filter order; score
desc then id asc).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Sequence

from kang.domain.memory.retrieval import ScoredRecord
from kang.domain.ports.context_recipe import ContextRecipe
from kang.domain.ports.embedding_index import EMBEDDABLE_STATUSES
from kang.domain.ports.memory_config import ASSEMBLY_CLASSES
from kang.domain.ports.memory_store import MemoryRecord

__all__ = [
    "MANIFEST_SCHEMA",
    "UNBUILT_CLASSES",
    "Allocation",
    "AssemblyItem",
    "ManifestMeta",
    "allocate",
    "build_manifest",
    "estimate_tokens",
    "render_context",
    "render_line",
    "suppression_reason",
]

MANIFEST_SCHEMA = 1
# ADR-058 D3: classes with no producer yet. Recorded empty, with this reason.
UNBUILT_CLASSES = {"p0": "not_built", "p3": "not_built", "p4": "not_built"}
EMPTY_CONTEXT = "(nothing relevant in memory)"


@dataclass(frozen=True)
class AssemblyItem:
    record: MemoryRecord
    klass: str  # "p1" | "p2"
    why: str  # "rule" | "pinned" | "profile" | "preference" | "relevance"
    scored: ScoredRecord | None  # P2 only
    line: str
    tokens: int


@dataclass(frozen=True)
class Allocation:
    included: tuple[AssemblyItem, ...]
    truncated: tuple[AssemblyItem, ...]
    used: dict[str, int]  # tokens used per class
    allowance: dict[str, int]  # tokens available per class, after cascade


@dataclass(frozen=True)
class ManifestMeta:
    invocation: str  # the correlation id
    agent: str
    recipe: ContextRecipe
    assembled_at: str
    query_sha256: str


def suppression_reason(record: MemoryRecord, recipe: ContextRecipe) -> str | None:
    """AG-009's filter order; the first failing filter names the reason."""
    if record.status not in EMBEDDABLE_STATUSES:
        return "status"
    if record.sensitivity == "private" or (
        record.sensitivity == "sensitive" and recipe.clearance != "sensitive"
    ):
        return "sensitivity"
    if record.type not in recipe.types:
        return "type"
    if record.trust_tier < recipe.tier_floor:
        return "tier"
    if record.confidence < recipe.confidence_floor:
        return "confidence"
    return None


def render_line(record: MemoryRecord) -> str:
    """06 §5.4: `[MEM:id] content — source, date, tier`; a contested record
    (`under_review`) is ⚠-tagged (06 Part XI)."""
    flag = "⚠ " if record.status == "under_review" else ""
    return (
        f"{flag}[MEM:{record.id}] {record.content} — {record.source_kind}, "
        f"{record.created_at[:10]}, tier {record.trust_tier}"
    )


def estimate_tokens(line: str) -> int:
    """Deterministic, model-independent estimate (ADR-058 D3)."""
    return len(line) // 4 + 1


def allocate(
    items: Sequence[AssemblyItem], budget_tokens: int, shares: dict[str, float]
) -> Allocation:
    """06 Part XI: each class gets its share of the budget plus whatever the
    class above left unused; within a class, items are kept in their given
    order until the next one does not fit, and everything from there down
    is truncated (bottom-up, recorded)."""
    included: list[AssemblyItem] = []
    truncated: list[AssemblyItem] = []
    used: dict[str, int] = {}
    allowance: dict[str, int] = {}
    carry = 0
    for klass in ASSEMBLY_CLASSES:
        allowance[klass] = int(budget_tokens * shares[klass]) + carry
        spent = 0
        cut = False
        for item in (i for i in items if i.klass == klass):
            if not cut and spent + item.tokens <= allowance[klass]:
                included.append(item)
                spent += item.tokens
            else:
                cut = True
                truncated.append(item)
        used[klass] = spent
        carry = allowance[klass] - spent
    return Allocation(tuple(included), tuple(truncated), used, allowance)


def render_context(included: Sequence[AssemblyItem]) -> str:
    if not included:
        return EMPTY_CONTEXT
    return "\n".join(item.line for item in included)


def _entry(item: AssemblyItem) -> dict:
    entry = {
        "id": item.record.id,
        "tier": item.record.trust_tier,
        "tokens": item.tokens,
        "why": item.why,
    }
    if item.scored is not None:
        entry["score"] = round(item.scored.score, 6)
        entry["terms"] = {k: round(v, 6) for k, v in vars(item.scored.terms).items()}
    return entry


def build_manifest(
    meta: ManifestMeta,
    allocation: Allocation | None,
    suppressed: dict[str, int],
    semantic: str,
    refused: str | None,
    budget_tokens: int,
) -> str:
    """ADR-058 D5: canonical (sorted keys, fixed separators), content-free
    JSON — ids, scores, tiers, tokens and a hash of the query. Same inputs,
    same bytes."""
    included = allocation.included if allocation else ()
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "invocation": meta.invocation,
        "agent": meta.agent,
        "recipe": {"id": meta.recipe.id, "version": meta.recipe.version},
        "assembled_at": meta.assembled_at,
        "query_sha256": meta.query_sha256,
        "budget": {
            "tokens": budget_tokens,
            "allowance": allocation.allowance if allocation else {},
            "used": allocation.used if allocation else {},
        },
        "standing": [_entry(i) for i in included if i.klass == "p1"],
        "relevance": [_entry(i) for i in included if i.klass == "p2"],
        "deterministic": {"items": [], "reason": UNBUILT_CLASSES["p0"]},
        "vault": {"items": [], "reason": UNBUILT_CLASSES["p3"]},
        "episodic": {"items": [], "reason": UNBUILT_CLASSES["p4"]},
        "truncated": [
            {"id": i.record.id, "class": i.klass, "reason": "budget"}
            for i in (allocation.truncated if allocation else ())
        ],
        "suppressed": dict(sorted(suppressed.items())),
        "semantic": semantic,
        "refused": refused,
    }
    return json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
