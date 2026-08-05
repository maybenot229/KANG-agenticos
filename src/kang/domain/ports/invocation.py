"""Invocation ledger port — the execution record `explain` reconstructs from.

Layer: domain/ports. Ports own their datatypes (17 §7).
Constitutional home: 12_API §4 (`invocation` is a resource), §12
(`explain.invocation` reconstructs from invocation rows + manifests + audit
in PERMANENT storage — never the event log, whose 90-day compaction would
break the ≥180-day guarantee: 15 §8.3), 05_AGENTS §14 (the reconstruction
test). This is the general execution ledger keyed by correlation_id: every
API operation writes one. Agent runs (M7) enrich rows with agent/task_class
+ manifest (07 §5.5's agent_invocation shape); at M4 the `manifest` is null
for plain commands.

Delta owed to 07_DATABASE §5.5: reconcile this general `invocation` ledger
with `agent_invocation` (the agent-specific projection) — recorded, not
silently applied.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

__all__ = ["Invocation", "InvocationNotFound", "InvocationStore"]

INVOCATION_KINDS = ("command", "query")  # 'agent' joins at M7
INVOCATION_OUTCOMES = ("ok", "failed", "degraded", "denied")


@dataclass(frozen=True)
class Invocation:
    """One execution: what ran, under whose authority, how it ended (12 §4).
    `manifest` is the context-assembly record for agent runs (Memory §5.4);
    null for commands/queries that assemble no context."""

    id: str
    correlation_id: str
    kind: str
    operation: str
    principal: str
    trigger: str  # 'kang' | 'cli' | 'job:{id}' | 'event:{type}'
    started: str
    finished: str | None
    outcome: str | None
    manifest: str | None = None


class InvocationNotFound(Exception):
    """No invocation with the given correlation_id."""


class InvocationStore(Protocol):
    """Append-then-finish: start an invocation, then record its outcome.
    Read back by correlation_id for `explain` (the ≥180-day guarantee)."""

    def start(self, invocation: Invocation) -> None:
        """Record an invocation beginning (finished/outcome null)."""
        ...

    def finish(self, invocation_id: str, outcome: str, finished: str) -> None:
        """Record the outcome. Idempotent re-finish is a no-op-safe overwrite."""
        ...

    def by_correlation(self, correlation_id: str) -> Invocation:
        """The invocation for this correlation_id, or raise
        InvocationNotFound — explain's primary source (12 §12)."""
        ...

    def recent(self, limit: int) -> list[Invocation]:
        """The most recent `limit` invocations, newest-`started`-first —
        the System-domain Invocations view's source (09_UI §12: "the
        agent run history... outcome badges, durations"). Not cursor-
        paginated (API-008 names cursor pagination as the default for
        "all list queries"); this is a single bounded page, the same
        simplification `deadline.list`/`held_action.list`/`audit.list`
        already made for their own bounded sets. Those three read a
        naturally-small set in full; this ledger grows with every
        command/query, so a hard `limit` (not merely "no filter yet")
        is the honest floor here, not the same shortcut restated —
        real cursor pagination remains open if this list ever needs to
        page past its first `limit` rows."""
        ...
