"""The memory write gate's handlers (ADR-051; 13 §2.8's memory-integrity suite,
opening claims) against fakes and a real PermissionEngine.

M-003 is the through-line: whatever a non-Kang principal sends, it lands in the
queue or is refused — never in `memory_record`.
"""

from __future__ import annotations

import itertools
from dataclasses import replace

import pytest

from kang.adapters.fakes.audit_log import FakeAuditLog
from kang.adapters.fakes.candidate_queue_store import FakeCandidateQueueStore
from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.delivery_store import FakeDeliveryStore
from kang.adapters.fakes.event_log import FakeEventLog
from kang.adapters.fakes.memory_store import FakeMemoryStore
from kang.adapters.fakes.recovery import FakeRecoveryApplier
from kang.adapters.fakes.sleeper import FakeSleeper
from kang.adapters.fakes.unit_of_work import FakeUnitOfWork
from kang.api.dispatch import HandlerContext
from kang.api.errors import ApiError
from kang.api.operations import (
    MemoryOpsDeps,
    make_candidate_list_handler,
    make_memory_handlers,
)
from kang.domain.ports.memory_config import MemoryConfig
from kang.kernel.audit.service import AuditService
from kang.kernel.bus.bus import EventBus
from kang.kernel.bus.delivery import Delivery
from kang.kernel.bus.reconciliation import Reconciliation
from kang.kernel.permissions.engine import PermissionDenied, PermissionEngine

DEVICE = "device-test"
STEWARD = "agent:memory_steward"

GRANTS = {
    "kernel:memory": ("events.publish:kang",),
    "kang": ("*",),
    STEWARD: (
        "memory.propose",
        "memory.propose:lesson",
        "memory.propose:preference",
        "memory.propose:observation",
        "candidates.expire",
    ),
}

KANG = HandlerContext("kang", "corr-k", "cli", first_party=True)
STEWARD_CTX = HandlerContext(STEWARD, "corr-s", STEWARD, first_party=False)

PARAMS = dict(
    type="lesson",
    content="I underestimate report time by about two times",
    trust_tier=1,
    source_kind="observed",
    source_detail="review-2026-w12",
    reason="a pattern across three retrospectives",
)


class Harness:
    def __init__(self, config=MemoryConfig(14), grants=GRANTS):
        self.clock = FakeClock()
        ids = (f"id-{n:04d}" for n in itertools.count())
        self.log = FakeEventLog(self.clock)
        self.audit_log = FakeAuditLog()
        audit = AuditService(self.audit_log, self.clock)
        engine = PermissionEngine(grants)
        bus = EventBus(
            self.log,
            Delivery(
                self.log,
                FakeDeliveryStore(self.clock),
                audit,
                dead_letter_id=lambda: "dl",
                sleeper=FakeSleeper(),
            ),
            Reconciliation(self.log, FakeRecoveryApplier(), audit, self.clock),
            engine,
            audit,
        )
        self.memory = FakeMemoryStore()
        self.queue = FakeCandidateQueueStore()
        self.deps = MemoryOpsDeps(
            bus=bus,
            memory=self.memory,
            queue=self.queue,
            unit_of_work=FakeUnitOfWork(self.memory, self.queue),
            permissions=engine,
            audit=audit,
            clock=self.clock,
            new_id=lambda: next(ids),
            device_id=DEVICE,
            config=config,
        )
        self.handlers = make_memory_handlers(self.deps)

    def call(self, operation, context, **params):
        return self.handlers[operation](context, params)

    def propose(self, context=KANG, **overrides):
        return self.call("memory.propose", context, **{**PARAMS, **overrides})

    def saved_events(self):
        stored = self.log.read_from(0)
        return [s.envelope for s in stored if s.envelope.type == "memory.saved"]

    def audit_actions(self):
        return [
            r.entry.action
            for m in self.audit_log.months()
            for r in self.audit_log.records(m)
        ]

    def audit_text(self):
        return repr(
            [
                r.entry
                for m in self.audit_log.months()
                for r in self.audit_log.records(m)
            ]
        )


@pytest.fixture
def h():
    return Harness()


def _all_records(h):
    return list(h.memory.snapshot().values())


# ------------------------------------------------------ Kang's auto-pass (D4)


def test_first_party_kang_proposal_lands_active_with_no_queue_row(h):
    result = h.propose()
    assert result["outcome"] == "admitted"
    record = h.memory.get(result["id"])
    assert (record.status, record.created_by, record.revision) == ("active", "kang", 1)
    assert h.queue.list_queue(10) == ()


def test_the_record_is_published_as_a_recovery_grade_memory_saved_event(h):
    result = h.propose()
    (event,) = h.saved_events()
    assert event.recovery_grade is True
    assert event.principal == "kernel:memory"
    assert event.payload["id"] == result["id"]
    assert event.payload["content"] == PARAMS["content"]
    assert "rowid" not in event.payload


def test_the_row_commits_only_inside_the_publish(h):
    """EB-004: an unauthorized publish (no `events.publish` grant for the
    memory principal) appends nothing AND commits no record."""
    bare = Harness(grants={"kang": ("*",)})
    with pytest.raises(PermissionDenied):
        bare.propose()
    assert _all_records(bare) == []
    assert bare.saved_events() == []


def test_every_gate_decision_is_audited_without_the_content(h):
    h.propose()
    h.propose(context=STEWARD_CTX, content="a different pattern of behavior")
    with pytest.raises(ApiError):
        h.propose(reason="")
    actions = h.audit_actions()
    for expected in (
        "memory.gate.admitted",
        "memory.gate.queued",
        "memory.gate.rejected",
    ):
        assert expected in actions
    assert PARAMS["content"] not in h.audit_text()
    assert "different pattern" not in h.audit_text()


# ------------------------------------------------- M-003: agents never admit


@pytest.mark.parametrize("confidence", [0.0, 0.5, 0.99, 1.0])
def test_an_agent_proposal_is_queued_never_admitted_at_any_confidence(h, confidence):
    result = h.propose(context=STEWARD_CTX, confidence=confidence)
    assert result["outcome"] == "queued"
    assert _all_records(h) == []
    candidate = h.queue.get(result["id"])
    assert candidate.pending
    assert candidate.payload["created_by"] == STEWARD
    assert candidate.payload["confidence"] == confidence


def test_a_body_field_cannot_claim_another_writer(h):
    result = h.propose(context=STEWARD_CTX, created_by="kang", first_party=True)
    assert h.queue.get(result["id"]).payload["created_by"] == STEWARD
    assert _all_records(h) == []


def test_kang_on_a_non_first_party_session_is_queued(h):
    plugin_session = HandlerContext("kang", "c", "plugin", first_party=False)
    assert h.propose(context=plugin_session)["outcome"] == "queued"
    assert _all_records(h) == []


def test_the_candidate_expires_at_the_configured_window(h):
    result = h.propose(context=STEWARD_CTX)
    assert result["expires_at"] == "2026-01-15T00:00:00+00:00"  # FakeClock + 14d
    assert (
        Harness(config=MemoryConfig(3)).propose(context=STEWARD_CTX)["expires_at"]
        == "2026-01-04T00:00:00+00:00"
    )


# ------------------------------------------------ the per-type scope (D2)


def test_a_type_the_principal_lacks_is_denied_and_one_it_holds_is_queued(h):
    with pytest.raises(ApiError) as denied:
        h.propose(context=STEWARD_CTX, type="fact")
    assert denied.value.code == "permission_denied"
    assert denied.value.details == {"scope": "memory.propose:fact"}
    assert h.propose(context=STEWARD_CTX, type="lesson")["outcome"] == "queued"
    assert _all_records(h) == []


def test_a_principal_holding_no_memory_scope_is_denied(h):
    nobody = HandlerContext("agent:chat", "c", "agent:chat", first_party=False)
    with pytest.raises(ApiError) as denied:
        h.propose(context=nobody)
    assert denied.value.code == "permission_denied"


# --------------------------------------------- the gate's other refusals (D6)


@pytest.mark.parametrize("mtype", ["rule", "profile"])
def test_rule_and_profile_from_a_non_kang_writer_are_refused_by_the_gate_itself(mtype):
    """Even if a grant slipped past the pairing lint (built here directly on
    PermissionEngine, which does not lint), the gate refuses a second time."""
    grants = {**GRANTS, STEWARD: (*GRANTS[STEWARD], f"memory.propose:{mtype}")}
    harness = Harness(grants=grants)
    with pytest.raises(ApiError) as refused:
        harness.propose(context=STEWARD_CTX, type=mtype)
    assert refused.value.details == {"code": "type_restricted"}
    assert _all_records(harness) == []
    assert harness.queue.list_queue(10) == ()


@pytest.mark.parametrize("mtype", ["rule", "profile"])
def test_first_party_kang_may_save_rule_and_profile(h, mtype):
    result = h.propose(type=mtype, trust_tier=2, source_kind="stated")
    assert result["outcome"] == "admitted"


@pytest.mark.parametrize("principal", ["rule:archive-retro", "plugin:notes"])
def test_rule_and_plugin_writers_are_refused(principal):
    grants = {**GRANTS, principal: ("memory.propose", "memory.propose:lesson")}
    harness = Harness(grants=grants)
    ctx = HandlerContext(principal, "c", principal, first_party=False)
    with pytest.raises(ApiError) as refused:
        harness.propose(context=ctx)
    assert refused.value.details == {"code": "writer_refused"}
    assert _all_records(harness) == [] and harness.queue.list_queue(10) == ()


@pytest.mark.parametrize("ctx", [KANG, STEWARD_CTX], ids=["kang", "agent"])
def test_private_sensitivity_is_refused_for_everyone(h, ctx):
    with pytest.raises(ApiError) as refused:
        h.propose(context=ctx, sensitivity="private")
    assert refused.value.details == {"code": "private_unsupported"}
    assert _all_records(h) == [] and h.queue.list_queue(10) == ()


@pytest.mark.parametrize(
    "overrides",
    [
        {"content": ""},
        {"reason": ""},
        {"reason": "   "},
        {"source_detail": ""},
        {"source_kind": "hearsay"},
        {"trust_tier": 9},
        {"confidence": 2.0},
        {"type": "not-a-type"},
    ],
)
@pytest.mark.parametrize("ctx", [KANG, STEWARD_CTX], ids=["kang", "agent"])
def test_absent_or_malformed_provenance_is_refused_and_writes_nothing(
    h, overrides, ctx
):
    with pytest.raises(ApiError) as refused:
        h.propose(context=ctx, **overrides)
    assert refused.value.code == "invalid_request"
    assert _all_records(h) == [] and h.queue.list_queue(10) == ()
    assert h.saved_events() == []


# ------------------------------------------------ exact-hash merge (D5)


def test_an_exact_duplicate_merges_instead_of_inserting_or_queueing():
    grants = {**GRANTS, STEWARD: (*GRANTS[STEWARD], "memory.propose:fact")}
    harness = Harness(grants=grants)
    first = harness.propose(type="fact", trust_tier=2, source_kind="stated")
    result = harness.propose(
        context=STEWARD_CTX,
        type="fact",
        content="  I UNDERESTIMATE report time   by about two TIMES ",
        source_detail="log-line-9",
    )
    assert result["outcome"] == "merged"
    assert result["id"] == first["id"]
    record = harness.memory.get(first["id"])
    assert record.revision == 2
    assert record.content == PARAMS["content"]  # content never changes
    assert "log-line-9" in record.source_detail
    assert len(_all_records(harness)) == 1
    assert harness.queue.list_queue(10) == ()
    revisions = [e.payload["revision"] for e in harness.saved_events()]
    assert revisions == [1, 2]
    assert "memory.gate.merged" in harness.audit_actions()


def test_the_same_source_is_not_appended_twice():
    grants = {**GRANTS, STEWARD: (*GRANTS[STEWARD], "memory.propose:fact")}
    harness = Harness(grants=grants)
    harness.propose(type="fact", trust_tier=2, source_kind="stated")
    for _ in range(2):
        harness.propose(context=STEWARD_CTX, type="fact", source_detail="same-source")
    record = next(iter(_all_records(harness)))
    assert record.source_detail.count("same-source") == 1
    assert record.revision == 3


# -------------------------------------------- memory.approve and friends


def _queued(h, **overrides):
    return h.propose(context=STEWARD_CTX, **overrides)["id"]


def test_approve_promotes_the_candidate_under_its_own_id(h):
    candidate_id = _queued(h)
    result = h.call("memory.approve", KANG, candidate_id=candidate_id)
    assert result == {"id": candidate_id, "revision": 1}
    record = h.memory.get(candidate_id)
    assert (record.status, record.created_by) == ("active", STEWARD)
    assert h.queue.get(candidate_id).resolved == "approved"
    (event,) = h.saved_events()
    assert event.payload["id"] == candidate_id


def test_edit_approve_lands_the_edited_content_as_revision_one(h):
    candidate_id = _queued(h)
    h.call(
        "memory.edit_approve", KANG, candidate_id=candidate_id, content="Edited by Kang"
    )
    record = h.memory.get(candidate_id)
    assert (record.content, record.revision) == ("Edited by Kang", 1)
    assert h.queue.get(candidate_id).resolved == "edited"


def test_edit_approve_refuses_empty_content_and_changes_nothing(h):
    candidate_id = _queued(h)
    with pytest.raises(ApiError):
        h.call("memory.edit_approve", KANG, candidate_id=candidate_id, content="  ")
    assert h.queue.get(candidate_id).pending and _all_records(h) == []


def test_reject_resolves_the_row_and_creates_no_record(h):
    candidate_id = _queued(h)
    assert h.call("memory.reject", KANG, candidate_id=candidate_id) == {
        "id": candidate_id,
        "resolved": "rejected",
    }
    assert h.queue.get(candidate_id).resolved == "rejected"
    assert _all_records(h) == [] and h.saved_events() == []


@pytest.mark.parametrize(
    "operation", ["memory.approve", "memory.edit_approve", "memory.reject"]
)
def test_only_first_party_kang_may_resolve_even_if_a_scope_was_granted(operation):
    """The `memory.approve` scope alone is not a door: the gate refuses any
    principal but first-party `kang`, so a wrong grant cannot open one."""
    grants = {**GRANTS, STEWARD: (*GRANTS[STEWARD], "memory.approve")}
    harness = Harness(grants=grants)
    candidate_id = _queued(harness)
    sessions = [
        STEWARD_CTX,
        HandlerContext(STEWARD, "c", "cli", first_party=True),
        HandlerContext("kang", "c", "plugin", first_party=False),
    ]
    for ctx in sessions:
        with pytest.raises(ApiError) as refused:
            harness.call(operation, ctx, candidate_id=candidate_id, content="x")
        assert refused.value.details == {"code": "approval_restricted"}
    assert harness.queue.get(candidate_id).pending
    assert _all_records(harness) == []


def test_approving_an_unknown_or_resolved_candidate_is_a_typed_error(h):
    with pytest.raises(ApiError) as missing:
        h.call("memory.approve", KANG, candidate_id="ghost")
    assert missing.value.code == "not_found"
    candidate_id = _queued(h)
    h.call("memory.reject", KANG, candidate_id=candidate_id)
    with pytest.raises(ApiError) as resolved:
        h.call("memory.approve", KANG, candidate_id=candidate_id)
    assert resolved.value.code == "conflict"
    assert _all_records(h) == []


def test_a_candidate_that_could_never_have_been_queued_cannot_be_approved(h):
    """The stored proposal is re-run through the gate as its proposer: a
    hand-planted `rule` candidate from an agent is refused at approval."""
    from kang.domain.memory import Proposal, proposal_payload
    from kang.domain.ports.candidate_queue_store import Candidate

    planted = Proposal("rule", "never schedule before 9", 2, "stated", "x", "why")
    h.queue.enqueue(
        Candidate(
            id="planted",
            payload=proposal_payload(planted, STEWARD, DEVICE),
            proposed_at="2026-01-01T00:00:00+00:00",
            expires_at="2026-01-15T00:00:00+00:00",
        )
    )
    with pytest.raises(ApiError) as refused:
        h.call("memory.approve", KANG, candidate_id="planted")
    assert refused.value.details == {"code": "type_restricted"}
    assert _all_records(h) == []


def test_approve_is_atomic_a_failed_resolution_leaves_no_record(h):
    candidate_id = _queued(h)

    def crash(*args):
        raise RuntimeError("crash between insert and resolve")

    h.queue.resolve = crash
    with pytest.raises(RuntimeError):
        h.call("memory.approve", KANG, candidate_id=candidate_id)
    assert h.memory.get(candidate_id) is None  # unit of work rolled the insert back
    assert h.queue.get(candidate_id).pending


# ------------------------------------------------------ candidate.expire (D9)


def _expire(h, ctx=STEWARD_CTX):
    return h.call("candidate.expire", ctx)


def test_expire_expires_only_rows_past_their_window_and_is_idempotent(h):
    stale = _queued(h)
    h.clock.advance(15 * 86400)
    fresh = _queued(h, content="a newer pattern I noticed later")
    result = _expire(h)
    assert result == {"expired": [stale], "count": 1}
    assert h.queue.get(stale).resolved == "expired"
    assert h.queue.get(fresh).pending
    assert _expire(h) == {"expired": [], "count": 0}
    assert _all_records(h) == []


def test_an_expired_candidate_can_no_longer_be_approved(h):
    stale = _queued(h)
    h.clock.advance(15 * 86400)
    _expire(h)
    with pytest.raises(ApiError) as refused:
        h.call("memory.approve", KANG, candidate_id=stale)
    assert refused.value.code == "conflict"
    assert _all_records(h) == []


# ------------------------------------------------------------ candidate.list


def test_candidate_list_shows_pending_first_oldest_first(h):
    first = _queued(h)
    h.clock.advance(60)
    second = _queued(h, content="another pattern worth noting")
    h.call("memory.reject", KANG, candidate_id=first)
    listing = make_candidate_list_handler(h.queue)(KANG, {})["candidates"]
    assert [c["id"] for c in listing] == [second, first]
    assert listing[0]["created_by"] == STEWARD and listing[1]["resolved"] == "rejected"
    assert "rowid" not in listing[0]


def test_candidate_list_clamps_a_non_positive_limit(h):
    _queued(h)
    assert (
        len(make_candidate_list_handler(h.queue)(KANG, {"limit": 0})["candidates"]) == 1
    )


# ------------------------------------------- memory.toml fails closed (D8)


def test_without_a_valid_memory_config_record_creating_ops_refuse():
    closed = Harness(config=None)
    for ctx in (KANG, STEWARD_CTX):
        with pytest.raises(ApiError) as refused:
            closed.propose(context=ctx)
        assert refused.value.code == "internal"
        assert "memory.toml" in refused.value.message
    assert _all_records(closed) == [] and closed.queue.list_queue(10) == ()


def test_without_a_config_approve_refuses_but_reject_and_expire_still_work():
    """Safe/silent-veto operations never need the gate's config: a broken
    install must not stop Kang rejecting, nor stop a stale queue expiring."""
    working = Harness()
    candidate_id = _queued(working)
    stale = _queued(working, content="a second pattern of behavior")
    closed = Harness(config=None)
    closed.queue = working.queue
    closed.deps = replace(closed.deps, queue=working.queue, memory=working.memory)
    closed.handlers = make_memory_handlers(closed.deps)
    with pytest.raises(ApiError):
        closed.call("memory.approve", KANG, candidate_id=candidate_id)
    assert (
        closed.call("memory.reject", KANG, candidate_id=candidate_id)["resolved"]
        == "rejected"
    )
    working.clock.advance(15 * 86400)
    closed.deps.clock.advance(15 * 86400)
    assert closed.call("candidate.expire", STEWARD_CTX)["expired"] == [stale]
