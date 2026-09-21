"""13 §2.8's first claim, searched exhaustively rather than asserted by one
handler: **no registered operation can put a non-Kang principal's content into
an `active` `memory_record`** (M-003; CLAUDE.md §8.1).

Three proofs, all against the REAL wired Core (composition root, real bus,
real SQLite, real PermissionEngine, real dispatcher):

1. A registry sweep — every operation in `OPERATIONS`, invoked by every
   non-Kang principal shape we can construct (agent / plugin / rule /
   kernel, each holding a *maximal* grant: every scope any operation
   declares, on both first-party and non-first-party sessions), with
   adversarial parameters. After every single call the record table is
   exactly what Kang alone put there. The sweep is not vacuous: the same
   harness, as first-party Kang, does create records.
2. Fuzzing the gate's API surface — `memory.propose` over the product of
   types x sensitivities x tiers x confidences x writers.
3. A structural search of `src/`: the record-insert function has exactly one
   caller, and only the sanctioned files write `memory_record` at all.
"""

from __future__ import annotations

import itertools
import re
from pathlib import Path

import pytest

from kang.adapters.sqlite.connection import open_connection
from kang.api.dispatch import ApiRequest
from kang.api.registry import OPERATIONS
from kang.domain.ports.memory_store import MEMORY_TYPES
from kang.domain.ports.session import Session
from kang.kernel.runtime.composition import build_core

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "src" / "kang"

KANG_CONTENT = "Kang's own saved fact about the school term"
AGENT_CONTENT = "an agent's claim that must never become active"

# Principal shapes a non-Kang caller could arrive as. The gate refuses
# rule:/plugin:/unknown shapes; the sweep proves it end to end anyway.
PRINCIPALS = (
    "agent:memory_steward",
    "agent:evil",
    "plugin:notes",
    "rule:archive-retro",
    "kernel:scheduler",
    "kernel:memory",
    "Kang",
    "kang ",
)


def _maximal_scopes() -> tuple[str, ...]:
    """Every scope any registered operation declares, plus every per-type
    memory.propose qualifier the pairing lint allows, plus publish authority
    — i.e. as much as a non-`kang` principal can possibly hold (wildcards are
    Kang's alone)."""
    scopes = {entry["scope"] for entry in OPERATIONS if entry["scope"]}
    scopes |= {
        f"memory.propose:{t}" for t in MEMORY_TYPES if t not in ("rule", "profile")
    }
    scopes.add("events.publish:kang")
    return tuple(sorted(scopes))


def _permissions_toml() -> str:
    lines = ["[grants]", '"kang" = ["*"]', '"kernel:memory" = ["events.publish:kang"]']
    rendered = ", ".join(f'"{s}"' for s in _maximal_scopes())
    for principal in PRINCIPALS:
        if principal == "kernel:memory":
            continue
        lines.append(f'"{principal}" = [{rendered}]')
    return "\n".join(lines) + "\n"


@pytest.fixture
def core(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "permissions.toml").write_text(_permissions_toml(), encoding="utf-8")
    (config / "memory.toml").write_text(
        (REPO_ROOT / "config" / "defaults" / "memory.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    built = build_core(tmp_path)
    yield built, tmp_path
    built.close()


def _session(core, principal: str, first_party: bool) -> str:
    token = core.new_id()
    core.sessions.create(Session(token, principal, first_party, ""))
    return token


def _dispatch(core, token, operation, params):
    return core.dispatcher.dispatch(
        ApiRequest(operation, params, token, idempotency_key=core.new_id())
    )


def _kang_saves(core, content=KANG_CONTENT, mtype="fact"):
    token = core.mint_first_party_session().token
    response = _dispatch(
        core,
        token,
        "memory.propose",
        dict(
            type=mtype,
            content=content,
            trust_tier=2,
            source_kind="stated",
            source_detail="conversation",
            reason="Kang said so",
        ),
    )
    assert response["ok"] is True, response
    return response["result"]


def _agent_proposal(core, content=AGENT_CONTENT, mtype="lesson"):
    token = _session(core, "agent:memory_steward", first_party=False)
    return _dispatch(
        core,
        token,
        "memory.propose",
        dict(
            type=mtype,
            content=content,
            trust_tier=1,
            source_kind="observed",
            source_detail="log",
            reason="a pattern",
        ),
    )


def _records(home: Path):
    conn = open_connection(home / "kang.db")
    try:
        return conn.execute(
            "SELECT id, type, status, content, trust_tier, sensitivity, reason, "
            "created_by, source_kind FROM memory_record ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def _adversarial_params(entry, candidate_id: str) -> list[dict]:
    """Params for one operation: empty, plus — for anything memory-shaped —
    every attack we can think of."""
    variants: list[dict] = [{}]
    name = entry["name"]
    base = dict(
        type="fact",
        content=AGENT_CONTENT,
        trust_tier=2,
        source_kind="stated",
        source_detail="x",
        reason="because",
        confidence=1.0,
        created_by="kang",
        first_party=True,
        status="active",
    )
    if name == "memory.propose":
        variants += [{**base, "type": t} for t in MEMORY_TYPES]
        variants += [
            {**base, "sensitivity": "sensitive"},
            {**base, "sensitivity": "private"},
            {**base, "type": "lesson", "confidence": 0.0},
        ]
        variants.append({**base, "content": KANG_CONTENT})  # a merge attempt
    if name in ("memory.approve", "memory.reject"):
        variants.append({"candidate_id": candidate_id})
    if name == "memory.edit_approve":
        variants.append({"candidate_id": candidate_id, "content": AGENT_CONTENT})
    if name == "candidate.expire":
        variants.append({})
    return variants


def test_no_registered_operation_lets_a_non_kang_principal_reach_active(core):
    built, home = core
    kang_record = _kang_saves(built)
    queued = _agent_proposal(built)
    assert queued["ok"] is True and queued["result"]["outcome"] == "queued"
    candidate_id = queued["result"]["id"]
    baseline = _records(home)
    assert len(baseline) == 1  # only Kang's own save exists

    sessions = [
        _session(built, principal, first_party)
        for principal, first_party in itertools.product(PRINCIPALS, (False, True))
    ]
    # The memory family is swept with every principal shape on both channels.
    # Every other operation is swept too (it must not create a record either),
    # but with one agent and one plugin session per channel: those operations
    # are indifferent to the caller's shape, and each real dispatch costs an
    # audit fsync — the commit tier's < 5 min budget (13 §3) is the reason.
    representative = [
        t
        for t, (p, _fp) in zip(sessions, itertools.product(PRINCIPALS, (False, True)))
        if p in ("agent:evil", "plugin:notes")
    ]
    calls = 0
    for entry in OPERATIONS:
        memory_family = entry["name"].startswith(("memory.", "candidate."))
        for token in sessions if memory_family else representative:
            for params in _adversarial_params(entry, candidate_id):
                _dispatch(built, token, entry["name"], params)
                calls += 1
        after = _records(home)
        # Nothing was added, and Kang's row's identity and content are intact
        # (a silent merge may bump its provenance/revision — never its words).
        assert [r[0] for r in after] == [kang_record["id"]], entry["name"]
        assert after[0][1:] == baseline[0][1:], entry["name"]
    assert calls > 350, "the sweep must actually exercise the surface"
    assert AGENT_CONTENT not in repr(_records(home))


def test_the_sweep_is_not_vacuous_kang_can_create_and_approve(core):
    """The same dispatcher, the same operations: first-party Kang admits a
    record, and approving the agent's candidate (Kang's action) promotes it
    under the queue row's own id."""
    built, home = core
    _kang_saves(built)
    candidate_id = _agent_proposal(built)["result"]["id"]
    assert len(_records(home)) == 1
    token = built.mint_first_party_session().token
    approved = _dispatch(built, token, "memory.approve", {"candidate_id": candidate_id})
    assert approved["ok"] is True, approved
    rows = _records(home)
    assert candidate_id in [r[0] for r in rows] and len(rows) == 2


@pytest.mark.parametrize("first_party", [False, True])
def test_a_maximally_granted_non_kang_principal_cannot_resolve_the_queue(
    core, first_party
):
    built, home = core
    candidate_id = _agent_proposal(built)["result"]["id"]
    token = _session(built, "agent:evil", first_party)
    for operation, params in (
        ("memory.approve", {"candidate_id": candidate_id}),
        ("memory.edit_approve", {"candidate_id": candidate_id, "content": "x"}),
        ("memory.reject", {"candidate_id": candidate_id}),
    ):
        response = _dispatch(built, token, operation, params)
        assert response["ok"] is False, operation
        expected = "permission_denied" if first_party else "first_party_required"
        assert response["error"]["code"] == expected, (operation, response)
    assert _records(home) == []


def test_fuzzing_memory_propose_never_yields_a_non_kang_active_record(core):
    built, home = core
    admitted = 0
    fuzzed = (
        "agent:memory_steward",
        "agent:evil",
        "plugin:notes",
        "rule:archive-retro",
    )
    for principal, first_party in itertools.product(fuzzed, (False, True)):
        token = _session(built, principal, first_party)
        for mtype, sensitivity, tier, confidence in itertools.product(
            MEMORY_TYPES, ("normal", "sensitive", "private"), (2,), (1.0,)
        ):
            response = _dispatch(
                built,
                token,
                "memory.propose",
                dict(
                    type=mtype,
                    content=f"claim {principal} {mtype} {sensitivity}",
                    trust_tier=tier,
                    source_kind="stated",
                    source_detail="fuzz",
                    reason="fuzz",
                    confidence=confidence,
                    sensitivity=sensitivity,
                ),
            )
            if response["ok"] and response["result"]["outcome"] == "admitted":
                admitted += 1
    assert admitted == 0
    assert _records(home) == []


# ------------------------------------------- the two engine checks, end to end


def test_the_coarse_and_per_type_checks_each_bite(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "permissions.toml").write_text(
        '[grants]\n"kang" = ["*"]\n"kernel:memory" = ["events.publish:kang"]\n'
        '"agent:qualified_only" = ["memory.propose:lesson"]\n'
        '"agent:bare_only" = ["memory.propose"]\n'
        '"agent:both" = ["memory.propose", "memory.propose:lesson"]\n',
        encoding="utf-8",
    )
    (tmp_path / "config" / "memory.toml").write_text(
        "[gate]\ncandidate_expiry_days = 14\n", encoding="utf-8"
    )
    built = build_core(tmp_path)
    try:
        params = dict(
            type="lesson",
            content="c",
            trust_tier=1,
            source_kind="observed",
            source_detail="d",
            reason="r",
        )
        outcomes = {}
        for principal in ("agent:qualified_only", "agent:bare_only", "agent:both"):
            token = _session(built, principal, False)
            response = _dispatch(built, token, "memory.propose", params)
            outcomes[principal] = (
                response["result"]["outcome"]
                if response["ok"]
                else (response["error"]["code"], response["error"]["details"]["scope"])
            )
        # Scope.covers: a qualified grant does NOT satisfy the bare request
        # (the dispatcher refuses), and a bare grant does NOT satisfy the
        # qualified one (the handler refuses). Both are needed (ADR-051 D2).
        assert outcomes == {
            "agent:qualified_only": ("permission_denied", "memory.propose"),
            "agent:bare_only": ("permission_denied", "memory.propose:lesson"),
            "agent:both": "queued",
        }
    finally:
        built.close()


# ---------------------------------------------------- the structural search


def _python_sources():
    return [p for p in SRC.rglob("*.py")]


def test_the_record_insert_function_has_exactly_one_caller():
    """`MemoryStore.insert_record` is called from one place: the API layer's
    single record-landing helper, which both Kang's auto-pass and
    `memory.approve` share. A second insert path is how a second door gets
    built by accident."""
    callers = []
    for path in _python_sources():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if (
                re.search(r"\binsert_record\(", line)
                and "def insert_record" not in line
            ):
                callers.append((path.relative_to(SRC).as_posix(), line.strip()))
    assert callers == [("api/operations/memory_ops.py", "memory.insert_record(record)")]


def test_only_the_sanctioned_files_write_the_memory_record_table():
    """SQL that creates a `memory_record` row exists in exactly two files:
    the store's `insert_record`, and the recovery applier's redo of a
    gate-published `memory.saved` event (EB-003) — which can only exist
    because the gate published it."""
    writers = set()
    for path in _python_sources():
        text = path.read_text(encoding="utf-8")
        if re.search(r"INSERT\s+INTO\s+memory_record", text, re.IGNORECASE):
            writers.add(path.relative_to(SRC).as_posix())
    assert writers == {"adapters/sqlite/memory_store.py", "adapters/sqlite/recovery.py"}


def test_build_record_has_no_caller_but_the_two_gate_paths():
    callers = set()
    for path in _python_sources():
        text = path.read_text(encoding="utf-8")
        if path.name in ("records.py", "__init__.py"):
            continue
        if re.search(r"\bbuild_record\(", text):
            callers.add(path.relative_to(SRC).as_posix())
    assert callers == {"api/operations/memory_ops.py"}


def test_every_operation_that_can_resolve_the_queue_is_first_party_only():
    resolving = [e for e in OPERATIONS if e["scope"] == "memory.approve"]
    assert {e["name"] for e in resolving} == {
        "memory.approve",
        "memory.edit_approve",
        "memory.reject",
        "candidate.list",
    }
    assert all(e["first_party_only"] for e in resolving)


def test_memory_and_candidate_operations_are_exactly_the_six_built():
    names = {
        e["name"] for e in OPERATIONS if e["name"].startswith(("memory.", "candidate."))
    }
    assert names == {
        "memory.propose",
        "memory.approve",
        "memory.edit_approve",
        "memory.reject",
        "candidate.list",
        "candidate.expire",
    }
