"""Memory wiring — the write gate's dependencies, the lifecycle operations'
dependencies, and this slice's `transactional_effects` entry (ADR-053 D8).

Layer: kernel/runtime, but exempt from the import matrix exactly as
`composition.py`/`scheduler_wiring.py`/`query_routing.py`/`model_wiring.py`
are (17 §4.3's composition-root exception) — `composition.py` was at 799 of
its 800-line hard limit when this slice's six operations arrived (ADR-053's
own Context: "a known, predicted cost of this slice"), so this is the split
ADR-023/037/044 each performed, done first per D8/the build brief, not after
hitting the lint. Registered by exact name in `tools/importlinter.toml`;
this is the fourth file, still one conceptual composition root, not a fifth
role. (Corrected 2026-10-05: it is the FIFTH file — `model_wiring.py`,
ADR-044, was already the fourth; ADR-053's own Verification records this,
and its D8 now carries the dated note.)

ADR-055 D7 adds the embedding worker's wiring here: `memory.embed`'s handler
over a `SqliteEmbeddingIndex` and the Core's one `Router` (its `embed`), so
`composition.py` — at its size limit — gains only the `router` input.

Constitutional home: 11_CODING §11 (composition root, plain constructor
calls), 17 §4.3, ADR-051 (the write gate's own wiring, moved here verbatim
— no behavior change), ADR-053 D3/D4/D7/D8.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from kang.adapters.config.memory_loader import (
    MemoryConfigError,
    load_assembly_config,
    load_memory_config,
    load_scoring_config,
)
from kang.adapters.config.recipes_loader import discover_recipes
from kang.adapters.sqlite.candidate_queue_store import SqliteCandidateQueueStore
from kang.adapters.sqlite.embedding_index import SqliteEmbeddingIndex
from kang.adapters.sqlite.memory_search import SqliteMemorySearchStore
from kang.adapters.sqlite.memory_store import SqliteMemoryStore
from kang.adapters.sqlite.transaction import SqliteUnitOfWork
from kang.api.operations import (
    ConfirmationDeps,
    MemoryEmbedDeps,
    MemoryLifecycleDeps,
    MemoryOpsDeps,
    MemorySearchDeps,
    make_memory_delete_effect,
    make_memory_embed_handler,
    make_memory_lifecycle_handlers,
    make_memory_search_handler,
)
from kang.domain.ports.backup import BackupService
from kang.domain.ports.held_action import HeldActionStore
from kang.kernel.audit.service import AuditService
from kang.kernel.bus.bus import EventBus
from kang.kernel.context.assembler import AssemblerDeps, ContextAssembler
from kang.kernel.permissions.engine import PermissionEngine
from kang.kernel.router.router import Router

__all__ = [
    "MemoryDeps",
    "MemoryWiringInputs",
    "build_memory_deps",
    "memory_handlers",
    "memory_transactional_effects",
]


@dataclass(frozen=True)
class MemoryWiringInputs:
    """Everything `build_memory_deps` needs, bundled (11 §4 — beyond a few
    parameters, a dataclass; the write gate's wiring and the lifecycle
    operations' wiring share almost all of it, so one input type serves
    both rather than two nearly-identical ones)."""

    kang_home: Path
    kang: object
    bus: EventBus
    permission_engine: PermissionEngine
    audit: AuditService
    backups: BackupService
    held_action_store: HeldActionStore
    clock: object
    new_id: Callable[[], str]
    device_id: str
    router: Router  # ADR-055 D7: the embedding worker's `embed`


@dataclass(frozen=True)
class MemoryDeps:
    """The write gate's deps and the lifecycle operations' deps, built
    together from one `MemoryWiringInputs` (D8)."""

    ops: MemoryOpsDeps
    lifecycle: MemoryLifecycleDeps
    embed: MemoryEmbedDeps  # ADR-055 D7
    search: MemorySearchDeps  # ADR-056
    assembler: ContextAssembler  # ADR-058


def build_memory_deps(inputs: MemoryWiringInputs) -> MemoryDeps:
    """ADR-051's write-gate wiring (moved out of `composition.py` verbatim
    — no behavior change) plus ADR-053 D3/D7's lifecycle wiring, built
    together since both close over the same live connection and clock.
    `memory.toml` is read here, fail-closed (ADR-051 D8): absent or
    malformed leaves `config=None`, so the record-creating operations
    refuse rather than default an expiry window. The two stores are
    separate `SqliteMemoryStore` instances over the same connection —
    both are stateless wrappers, so there is nothing to coordinate."""
    try:
        config = load_memory_config(inputs.kang_home / "config" / "memory.toml")
    except MemoryConfigError:
        config = None
    ops = MemoryOpsDeps(
        bus=inputs.bus,
        memory=SqliteMemoryStore(inputs.kang),
        queue=SqliteCandidateQueueStore(inputs.kang),
        unit_of_work=SqliteUnitOfWork(inputs.kang),
        permissions=inputs.permission_engine,
        audit=inputs.audit,
        clock=inputs.clock,
        new_id=inputs.new_id,
        device_id=inputs.device_id,
        config=config,
    )
    lifecycle = MemoryLifecycleDeps(
        bus=inputs.bus,
        memory=SqliteMemoryStore(inputs.kang),
        backups=inputs.backups,
        confirmation=ConfirmationDeps(
            inputs.held_action_store, inputs.clock, inputs.new_id
        ),
        audit=inputs.audit,
        clock=inputs.clock,
        new_id=inputs.new_id,
        device_id=inputs.device_id,
    )
    embed = MemoryEmbedDeps(
        index=SqliteEmbeddingIndex(inputs.kang),
        embed=inputs.router.embed,
        audit=inputs.audit,
    )
    search = _search_deps(inputs)
    return MemoryDeps(
        ops=ops,
        lifecycle=lifecycle,
        embed=embed,
        search=search,
        assembler=_assembler(inputs, search),
    )


def _search_deps(inputs: MemoryWiringInputs) -> MemorySearchDeps:
    """ADR-056: `memory.search` over the same live connection. Its own
    `[scoring]`/`[search]` fail closed only for search (D3): absent or
    malformed leaves `config=None`, and the gate is untouched."""
    try:
        config = load_scoring_config(inputs.kang_home / "config" / "memory.toml")
    except MemoryConfigError:
        config = None
    return MemorySearchDeps(
        store=SqliteMemorySearchStore(inputs.kang),
        index=SqliteEmbeddingIndex(inputs.kang),
        embed=inputs.router.embed,
        audit=inputs.audit,
        clock=inputs.clock,
        config=config,
    )


# ADR-058 D2: shipped recipes, beside the agent definitions.
ASSEMBLY_DIR = Path(__file__).resolve().parents[2] / "agents" / "assembly"


def _assembler(
    inputs: MemoryWiringInputs, search: MemorySearchDeps
) -> ContextAssembler:
    """ADR-058: the kernel Context Assembler over the same connection, the
    same scoring config `memory.search` uses, and its own `[assembly]`
    budget shares — each failing closed for assembly only (the assembler
    records `refused: config` rather than defaulting). Recipes are shipped
    code: a malformed one raises and refuses boot, like an agent definition."""
    try:
        assembly = load_assembly_config(inputs.kang_home / "config" / "memory.toml")
    except MemoryConfigError:
        assembly = None
    return ContextAssembler(
        AssemblerDeps(
            store=search.store,
            index=search.index,
            embed=search.embed,
            scoring=search.config,
            assembly=assembly,
            recipes=discover_recipes(ASSEMBLY_DIR),
            permissions=inputs.permission_engine,
            clock=inputs.clock,
        )
    )


def memory_handlers(deps: MemoryDeps) -> dict[str, Any]:
    """`composition.py::_build_handlers`'s own entry point into ADR-053's six
    lifecycle operations, ADR-055's `memory.embed` and ADR-056's
    `memory.search`."""
    return {
        **make_memory_lifecycle_handlers(deps.lifecycle),
        "memory.embed": make_memory_embed_handler(deps.embed),
        # ADR-056 D7: a query, wired here (the write executor) rather than
        # in query_routing's read pool — the Router's ledger write needs
        # the write connection.
        "memory.search": make_memory_search_handler(deps.search),
    }


def memory_transactional_effects(
    deps: MemoryLifecycleDeps,
) -> dict[str, Callable[[dict[str, Any]], None]]:
    """ADR-053 D4/D8: this slice's own `transactional_effects` entry —
    `composition.py::_build_consequential_handlers` merges this into its
    own table (`_check_transactional_effects_registered`'s startup gate
    proves the pairing, exactly as it already does for job.disable/
    .enable)."""
    return {
        "memory.delete": make_memory_delete_effect(deps.memory, deps.audit, deps.clock)
    }
