"""Cycle defense (EB-011): static graph lint + runtime causation-depth guard.

Both layers proven: a declared cycle is named and rejected; a synthetic
causation chain halts exactly at the cap. The static lint's real job graph
arrives with the scheduler (M3) — the mechanism is proven now.
"""

from __future__ import annotations

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.event_log import FakeEventLog
from kang.kernel.bus.cycle_defense import (
    MAX_CAUSATION_DEPTH,
    CausationDepthExceeded,
    DeclaredCycleError,
    causation_depth,
    check_no_cycles,
    find_cycle,
    guard_causation_depth,
)
from tests.fixtures.event_log_contract import make_envelope

# -- static lint (EB-011.1) -----------------------------------------------


def test_acyclic_graph_has_no_cycle():
    graph = {"a": ["b"], "b": ["c"], "c": []}
    assert find_cycle(graph) is None
    check_no_cycles(graph)  # does not raise


def test_direct_cycle_is_found_and_named():
    graph = {"deadline.approaching": ["job:plan"], "job:plan": ["deadline.approaching"]}
    cycle = find_cycle(graph)
    assert cycle is not None
    assert cycle[0] == cycle[-1]  # closed loop
    with pytest.raises(DeclaredCycleError, match="cycle"):
        check_no_cycles(graph)


def test_indirect_cycle_is_found():
    graph = {"a": ["b"], "b": ["c"], "c": ["a"]}
    with pytest.raises(DeclaredCycleError):
        check_no_cycles(graph)


def test_self_loop_is_a_cycle():
    with pytest.raises(DeclaredCycleError):
        check_no_cycles({"a": ["a"]})


# -- runtime depth guard (EB-011.2) ---------------------------------------


def _chain(log: FakeEventLog, length: int) -> str | None:
    """Append a causation chain of `length` events; return the last id."""
    parent = None
    for index in range(length):
        event_id = f"event-{index:04d}"
        log.append(make_envelope(index, event_id=event_id, causation_id=parent))
        parent = event_id
    return parent


def test_root_event_has_depth_zero():
    log = FakeEventLog(FakeClock())
    assert causation_depth(log, None) == 0


def test_depth_counts_ancestors():
    log = FakeEventLog(FakeClock())
    last = _chain(log, 3)  # event-0 <- event-1 <- event-2
    assert causation_depth(log, last) == 3


def test_guard_allows_below_cap():
    log = FakeEventLog(FakeClock())
    last = _chain(log, MAX_CAUSATION_DEPTH - 1)
    guard_causation_depth(log, last)  # depth 15, does not raise


def test_guard_refuses_at_cap():
    log = FakeEventLog(FakeClock())
    last = _chain(log, MAX_CAUSATION_DEPTH)  # depth 16
    with pytest.raises(CausationDepthExceeded, match="cap"):
        guard_causation_depth(log, last)


def test_missing_parent_ends_the_walk():
    log = FakeEventLog(FakeClock())
    # cite a parent that was compacted out of retention
    assert causation_depth(log, "event-gone") == 1
