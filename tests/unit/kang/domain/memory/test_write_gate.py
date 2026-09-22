"""The write gate as pure policy (ADR-051 D4-D6; 06_MEMORY Part IV; M-003).

No database, no ports, no I/O: every admission rule is provable against
nothing at all. The exhaustive product test is the M-003 claim at the policy
level — `admit` is reachable by exactly one identity.
"""

from __future__ import annotations

import itertools
from dataclasses import replace

import pytest

from kang.domain.memory import (
    GateProbes,
    Proposal,
    Writer,
    authorize_resolution,
    decide,
    validate_proposal,
)
from kang.domain.ports.memory_store import (
    MEMORY_TYPES,
    SENSITIVITIES,
    SOURCE_KINDS,
    TRUST_TIERS,
    content_fingerprint,
)

KANG = Writer("kang", first_party=True)
AGENT = Writer("agent:memory_steward", first_party=False)
NO_PROBES = GateProbes()


def proposal(**overrides) -> Proposal:
    # trust_tier=1: a typical AI-observed default (06 §2.1). Tests that
    # specifically exercise Tier 2 (ADR-052 D2) pass trust_tier=2 explicitly
    # — a proposal() default of 2 would silently shadow every other AGENT
    # test behind tier_restricted.
    base = dict(
        type="fact",
        content="School term ends June 12",
        trust_tier=1,
        source_kind="stated",
        source_detail="conversation",
        reason="Kang said so",
    )
    base.update(overrides)
    return Proposal(**base)


# ---------------------------------------------------------------- M-003


WRITERS = [
    Writer("kang", True),
    Writer("kang", False),
    Writer("agent:memory_steward", True),
    Writer("agent:memory_steward", False),
    Writer("agent:chat", False),
    Writer("rule:project-archived", True),
    Writer("rule:project-archived", False),
    Writer("plugin:notes", True),
    Writer("plugin:notes", False),
    Writer("kernel:scheduler", True),
    Writer("system", False),
    Writer("kang ", True),
    Writer("Kang", True),
    Writer("kang:impersonator", True),
    Writer("", False),
]


def test_only_first_party_kang_can_ever_be_admitted():
    """Exhaust writers x types x sensitivities x confidences x tiers x
    duplicate-probe: `admit` is never returned for anyone but principal
    exactly `kang` on a first-party session. No argument changes that."""
    admitted = set()
    for writer, mtype, sensitivity, confidence, tier, dup in itertools.product(
        WRITERS,
        MEMORY_TYPES,
        SENSITIVITIES,
        (0.0, 0.5, 0.9, 0.99, 1.0),
        TRUST_TIERS,
        (None, "existing-id"),
    ):
        decision = decide(
            proposal(
                type=mtype,
                sensitivity=sensitivity,
                confidence=confidence,
                trust_tier=tier,
            ),
            writer,
            GateProbes(exact_duplicate_id=dup),
        )
        if decision.outcome == "admit":
            admitted.add((writer.principal, writer.first_party))
    assert admitted == {("kang", True)}


def test_merge_is_reachable_only_by_kang():
    """ADR-052 D1's own exhaustive proof, mirroring the admit-set sweep
    above: `merge` is never returned for anyone but principal exactly
    `kang` on a first-party session, regardless of type, sensitivity,
    confidence, or tier."""
    merged = set()
    for writer, mtype, sensitivity, confidence, tier in itertools.product(
        WRITERS,
        MEMORY_TYPES,
        SENSITIVITIES,
        (0.0, 0.5, 0.9, 0.99, 1.0),
        TRUST_TIERS,
    ):
        decision = decide(
            proposal(
                type=mtype,
                sensitivity=sensitivity,
                confidence=confidence,
                trust_tier=tier,
            ),
            writer,
            GateProbes(exact_duplicate_id="mem-1"),
        )
        if decision.outcome == "merge":
            merged.add((writer.principal, writer.first_party))
    assert merged == {("kang", True)}


@pytest.mark.parametrize("confidence", [0.0, 0.5, 0.95, 0.999, 1.0])
def test_no_confidence_value_admits_an_agent_proposal(confidence):
    decision = decide(proposal(confidence=confidence), AGENT, NO_PROBES)
    assert decision.outcome == "queue"


def test_a_valid_agent_proposal_is_queued():
    decision = decide(proposal(), AGENT, NO_PROBES)
    assert decision.outcome == "queue"
    assert decision.code is None


def test_kang_on_a_non_first_party_session_is_queued_not_admitted():
    decision = decide(proposal(), Writer("kang", first_party=False), NO_PROBES)
    assert decision.outcome == "queue"


def test_first_party_kang_is_admitted_with_no_queue():
    decision = decide(proposal(), KANG, NO_PROBES)
    assert decision.outcome == "admit"


# --------------------------------------------------- 06 §4.2 required metadata


@pytest.mark.parametrize(
    "overrides",
    [
        {"type": "not-a-type"},
        {"content": ""},
        {"content": "   \n\t"},
        {"trust_tier": 3},
        {"trust_tier": -1},
        {"source_kind": "hearsay"},
        {"source_detail": ""},
        {"source_detail": "  "},
        {"reason": ""},
        {"reason": " "},
        {"confidence": -0.01},
        {"confidence": 1.01},
        {"sensitivity": "secret"},
    ],
)
@pytest.mark.parametrize("writer", [KANG, AGENT], ids=["kang", "agent"])
def test_absent_or_malformed_provenance_is_rejected_for_every_writer(overrides, writer):
    decision = decide(proposal(**overrides), writer, NO_PROBES)
    assert decision.outcome == "reject"
    assert decision.code == "invalid"
    assert validate_proposal(proposal(**overrides)) is not None


def test_a_complete_proposal_validates():
    assert validate_proposal(proposal()) is None


def test_every_catalog_source_kind_and_tier_validates():
    for kind, tier in itertools.product(SOURCE_KINDS, TRUST_TIERS):
        assert validate_proposal(proposal(source_kind=kind, trust_tier=tier)) is None


# --------------------------------------------------------------- D6 refusals


@pytest.mark.parametrize("principal", ["rule:archive-retro", "plugin:notes"])
@pytest.mark.parametrize("first_party", [True, False])
def test_rule_and_plugin_writers_are_refused(principal, first_party):
    decision = decide(proposal(), Writer(principal, first_party), NO_PROBES)
    assert (decision.outcome, decision.code) == ("reject", "writer_refused")


@pytest.mark.parametrize("principal", ["kernel:scheduler", "system", "", "kang:x"])
def test_an_unaccountable_principal_shape_is_refused(principal):
    decision = decide(proposal(), Writer(principal, True), NO_PROBES)
    assert (decision.outcome, decision.code) == ("reject", "writer_refused")


@pytest.mark.parametrize("writer", [KANG, AGENT], ids=["kang", "agent"])
def test_private_sensitivity_is_refused_for_everyone(writer):
    decision = decide(proposal(sensitivity="private"), writer, NO_PROBES)
    assert (decision.outcome, decision.code) == ("reject", "private_unsupported")


@pytest.mark.parametrize("mtype", ["rule", "profile"])
def test_rule_and_profile_are_refused_for_a_non_kang_writer(mtype):
    decision = decide(proposal(type=mtype), AGENT, NO_PROBES)
    assert (decision.outcome, decision.code) == ("reject", "type_restricted")
    non_first_party_kang = Writer("kang", first_party=False)
    assert decide(proposal(type=mtype), non_first_party_kang, NO_PROBES).code == (
        "type_restricted"
    )


@pytest.mark.parametrize("mtype", ["rule", "profile"])
def test_first_party_kang_may_write_rule_and_profile(mtype):
    assert decide(proposal(type=mtype), KANG, NO_PROBES).outcome == "admit"


# ------------------------------------------------------------- D5 duplicates


def test_an_exact_duplicate_from_an_agent_is_rejected_never_merged():
    """ADR-052 D1: only Kang's own exact duplicate ever reaches
    `merge_provenance` — every other writer's duplicate is a plain
    rejection, never a mutation of the active row."""
    decision = decide(proposal(), AGENT, GateProbes(exact_duplicate_id="mem-1"))
    assert (decision.outcome, decision.code, decision.merge_into) == (
        "reject",
        "duplicate",
        None,
    )


def test_the_duplicate_rejection_names_neither_the_incumbent_nor_its_content():
    """ADR-052 D1's deliberate side-channel narrowing: the caller learns
    "duplicate", never which record or what it says."""
    decision = decide(
        proposal(content="a very distinctive sentence"),
        AGENT,
        GateProbes(exact_duplicate_id="mem-secret-id"),
    )
    assert "mem-secret-id" not in decision.reason
    assert "a very distinctive sentence" not in decision.reason


@pytest.mark.parametrize(
    "writer",
    [
        AGENT,
        Writer("agent:chat", False),
        Writer("agent:memory_steward", True),  # first-party ≠ kang
        Writer("kang", first_party=False),  # principal "kang", not is_kang
    ],
)
def test_no_non_kang_writer_ever_reaches_merge(writer):
    decision = decide(proposal(), writer, GateProbes(exact_duplicate_id="mem-1"))
    assert decision.outcome != "merge"


def test_an_exact_duplicate_merges_for_kang_instead_of_inserting():
    decision = decide(proposal(), KANG, GateProbes(exact_duplicate_id="mem-1"))
    assert (decision.outcome, decision.merge_into) == ("merge", "mem-1")


def test_a_refused_writer_never_reaches_the_merge_branch():
    decision = decide(
        proposal(), Writer("rule:x", True), GateProbes(exact_duplicate_id="mem-1")
    )
    assert decision.outcome == "reject"
    assert decision.code == "writer_refused"  # caught before the duplicate probe


def test_a_restricted_type_never_merges_for_an_agent():
    decision = decide(
        proposal(type="rule"), AGENT, GateProbes(exact_duplicate_id="mem-1")
    )
    assert decision.outcome == "reject"
    assert decision.code == "type_restricted"  # caught before the duplicate probe


# ------------------------------------------------------- D2 Tier 2 restriction


@pytest.mark.parametrize("writer", [AGENT, Writer("kang", first_party=False)])
def test_a_non_kang_tier_2_proposal_is_refused(writer):
    decision = decide(proposal(trust_tier=2), writer, NO_PROBES)
    assert (decision.outcome, decision.code) == ("reject", "tier_restricted")


def test_first_party_kang_may_propose_tier_2():
    decision = decide(proposal(trust_tier=2), KANG, NO_PROBES)
    assert decision.outcome == "admit"


@pytest.mark.parametrize("tier", [0, 1])
def test_a_non_kang_writer_may_propose_tier_0_or_1(tier):
    decision = decide(proposal(trust_tier=tier), AGENT, NO_PROBES)
    assert decision.outcome == "queue"


def test_tier_restricted_is_refused_before_the_duplicate_probe_fires():
    """ADR-052 D2: placed with the writer-class refusals — a false sanction
    claim is refused whether or not the content happens to duplicate
    something. Proven by giving it a duplicate probe that WOULD merge if the
    tier check were skipped or came later, and asserting the code is still
    `tier_restricted`, not `duplicate`."""
    decision = decide(
        proposal(trust_tier=2), AGENT, GateProbes(exact_duplicate_id="mem-1")
    )
    assert (decision.outcome, decision.code) == ("reject", "tier_restricted")


def test_tier_restricted_is_refused_before_a_kang_would_have_merged_too():
    """Same proof from the other side: a non-Kang tier-2 duplicate never
    even reaches the branch that decides Kang-vs-not for merging."""
    decision = decide(
        proposal(trust_tier=2),
        Writer("kang", first_party=False),
        GateProbes(exact_duplicate_id="mem-1"),
    )
    assert decision.code == "tier_restricted"


def test_the_fingerprint_folds_case_and_whitespace():
    a = content_fingerprint("School  term ends\nJune 12")
    b = content_fingerprint("  school term ends june 12 ")
    assert a == b
    assert a != content_fingerprint("school term ends june 13")


# --------------------------------------------------------- resolution authority


def test_only_first_party_kang_may_resolve_the_queue():
    assert authorize_resolution(KANG) is None
    for writer in WRITERS:
        if (writer.principal, writer.first_party) == ("kang", True):
            continue
        refusal = authorize_resolution(writer)
        assert refusal is not None
        assert (refusal.outcome, refusal.code) == ("reject", "approval_restricted")


def test_the_gate_is_deterministic():
    p = proposal()
    assert decide(p, AGENT, NO_PROBES) == decide(replace(p), AGENT, NO_PROBES)
