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
role.

Constitutional home: 11_CODING §11 (composition root, plain constructor
calls), 17 §4.3, ADR-051 (the write gate's own wiring, moved here verbatim
— no behavior change), ADR-053 D3/D4/D7/D8.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from kang.adapters.config.memory_loader import MemoryConfigError, load_memory_config
from kang.adapters.sqlite.candidate_queue_store import SqliteCandidateQueueStore
from kang.adapters.sqlite.memory_store import SqliteMemoryStore
from kang.adapters.sqlite.transaction import SqliteUnitOfWork
from kang.api.operations import (
    ConfirmationDeps,
    MemoryLifecycleDeps,
    MemoryOpsDeps,
    make_memory_delete_effect,
    make_memory_lifecycle_handlers,
)
from kang.domain.ports.backup import BackupService
from kang.domain.ports.held_action import HeldActionStore
from kang.kernel.audit.service import AuditService
from kang.kernel.bus.bus import EventBus
from kang.kernel.permissions.engine import PermissionEngine

__all__ = [
    "MemoryDeps",
    "MemoryWiringInputs",
    "build_memory_deps",
    "memory_lifecycle_handlers",
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


@dataclass(frozen=True)
class MemoryDeps:
    """The write gate's deps and the lifecycle operations' deps, built
    together from one `MemoryWiringInputs` (D8)."""

    ops: MemoryOpsDeps
    lifecycle: MemoryLifecycleDeps


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
    return MemoryDeps(ops=ops, lifecycle=lifecycle)


def memory_lifecycle_handlers(deps: MemoryLifecycleDeps) -> dict[str, Any]:
    """`composition.py::_build_handlers`'s own entry point into this
    slice's six operations."""
    return make_memory_lifecycle_handlers(deps)


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
