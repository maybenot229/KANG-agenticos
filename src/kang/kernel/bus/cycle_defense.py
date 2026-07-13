"""Cycle defense — the two layers of EB-011.

Layer: kernel/bus.
Constitutional home: 15_EVENT_BUS EB-011.1 (static lint: reject a declared
event→job→event graph containing a cycle, naming it) and EB-011.2 (runtime
causation-depth guard: a causation chain deeper than 16 must not publish
further). Neither alone suffices — the static lint cannot see
data-dependent loops; the depth guard is reactive and cannot name a
definition. Both are REQUIRED.

The static lint's real input — event-triggered job definitions (D014) —
does not exist until the scheduler (M3); `find_cycle` is the mechanism,
unit-tested on synthetic graphs now, wired to definitions then.
"""

from __future__ import annotations

from kang.domain.ports.eventlog import EventLog

__all__ = [
    "CausationDepthExceeded",
    "DeclaredCycleError",
    "MAX_CAUSATION_DEPTH",
    "causation_depth",
    "check_no_cycles",
    "find_cycle",
    "guard_causation_depth",
]

# EB-011.2: legitimate KANG chains observed in the pipeline catalog are
# ≤ 5 deep; the cap is a config value with an audit entry, not an ADR.
MAX_CAUSATION_DEPTH = 16


class DeclaredCycleError(Exception):
    """A declared event→job→event graph contains a cycle (EB-011.1)."""


class CausationDepthExceeded(Exception):
    """A causation chain would exceed MAX_CAUSATION_DEPTH (EB-011.2)."""


def find_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    """Return one cycle as a node path (first repeat closes it), or None.
    Pure DFS with a recursion stack — the static lint's engine (EB-011.1)."""
    visited: set[str] = set()

    def walk(node: str, path: list[str], on_stack: set[str]) -> list[str] | None:
        visited.add(node)
        on_stack.add(node)
        path.append(node)
        for neighbour in graph.get(node, ()):
            if neighbour in on_stack:
                return path[path.index(neighbour) :] + [neighbour]
            if neighbour not in visited:
                found = walk(neighbour, path, on_stack)
                if found is not None:
                    return found
        path.pop()
        on_stack.discard(node)
        return None

    for start in graph:
        if start not in visited:
            cycle = walk(start, [], set())
            if cycle is not None:
                return cycle
    return None


def check_no_cycles(graph: dict[str, list[str]]) -> None:
    """Reject a declared graph containing a cycle, naming it (EB-011.1)."""
    cycle = find_cycle(graph)
    if cycle is not None:
        raise DeclaredCycleError("declared event→job→event cycle: " + " → ".join(cycle))


def causation_depth(event_log: EventLog, causation_id: str | None) -> int:
    """Depth of the causation chain a new event would extend: the number of
    ancestors reachable by walking `causation_id` parents (EB-011.2). A root
    cause (causation_id is None) has depth 0. Missing parents end the walk
    (an event may cite a parent already compacted out of retention)."""
    depth = 0
    parent_id = causation_id
    seen: set[str] = set()
    while parent_id is not None and parent_id not in seen:
        seen.add(parent_id)
        depth += 1
        parent = event_log.find_by_event_id(parent_id)
        if parent is None:
            break
        parent_id = parent.envelope.causation_id
    return depth


def guard_causation_depth(event_log: EventLog, causation_id: str | None) -> None:
    """Refuse to extend a chain past the cap (EB-011.2)."""
    depth = causation_depth(event_log, causation_id)
    if depth >= MAX_CAUSATION_DEPTH:
        raise CausationDepthExceeded(
            f"causation chain depth {depth} reaches the cap "
            f"{MAX_CAUSATION_DEPTH}; refusing to publish further (EB-011.2)"
        )
