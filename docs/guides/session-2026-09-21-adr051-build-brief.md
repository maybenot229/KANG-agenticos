# Build brief — implementing ADR-051 (the memory write gate)

**Written:** 2026-09-21, by the session that drafted ADR-051.
**For:** the coding session that implements it.
**Precondition — check before touching anything:** `docs/adr/051-memory-write-gate.md` must say `**Status:** accepted`. If it still says `proposed`, stop, say so, and end your turn.
**Non-normative** (17 §12). ADR beats brief; a numbered document beats the ADR except where the ADR's "Affected documents" line names the amendment. A third disagreement: stop and surface it.

> **This is the most safety-critical slice in Phase 2.** 06_MEMORY calls the gate the single most safety-critical component, and M-003 — AI proposals never auto-commit at any confidence — is the decision it makes mechanical. If at any point a change you are about to make would create a second way for a non-Kang principal to reach an `active` memory record, stop and surface it instead of writing it. There is no deadline pressure on this slice that outranks that.

---

## 0. What you are building

The write gate as pure domain policy, two new ports with fakes and SQLite adapters, six operations, one registered event with its recovery applier, a fail-closed `memory.toml`, and a second `memory_steward` job. Plus the tests that open 13 §2.8's memory-integrity suite, and five dated document amendments.

## 1. Read first, in this order, each in full

1. `CLAUDE.md` (repo root) — §8 and §9. §8.1 ("bypass or weaken the memory write gate, for any reason") is about the thing you are building.
2. `docs/adr/051-memory-write-gate.md` — D1–D10. Its Consequences list what is deliberately weaker than the spec; do not "improve" any of those.
3. `docs/06_MEMORY.md` **Part IV entire** (§4.1 writers table, §4.2 pipeline and required metadata, §4.3 queue contract), plus M-003, M-002, §8.1, §12.1, §12.2, Appendix A.
4. `docs/adr/048-memory-truth-schema.md` D1 (the candidate's identity contract you implement) and `migrations/0020_memory_truth_schema.sql` + `0021_memory_revision_device_id.sql` — the real columns, not 07's prose.
5. `docs/12_API.md` §10, §4, API-003, API-006. `docs/15_EVENT_BUS.md` EB-003, EB-004, §6.1, §6.3.
6. `src/kang/kernel/permissions/scope.py` — read `Scope.covers` before writing any grant. ADR-051 D2 exists because of its exact semantics.
7. Pattern sources to copy rather than invent: `src/kang/domain/deadlines/` (a domain service's shape), `src/kang/api/operations/deadline_ops.py` (a handler that publishes-then-commits), `src/kang/adapters/sqlite/recovery.py` (the applier shape), `src/kang/kernel/bus/event_registry.py` (an `EventType` entry), `src/kang/adapters/config/permissions_loader.py` (a fail-closed loader), `src/kang/api/operations/conversation_ops.py` + `kernel/runtime/scheduler_wiring.py` (ADR-047's job wiring, which D9 mirrors exactly), `tests/fixtures/conversation_store_contract.py` (a port contract suite).
8. `tests/suites/CLAIMS.md`; `docs/13_TESTING.md` §2.8.

## 2. Suggested order of work

Build it in this order so each step is provable before the next depends on it. Run the fast tests as you go; do not leave all verification to the end.

1. **`domain/memory/write_gate.py` first, with its unit tests, before any I/O exists.** A pure function: proposal + writer identity + probe results → typed `GateDecision`. Every rule in 06 §4.1/§4.2 and ADR-051 D4/D6 is testable here against no database at all. If a rule is hard to test here, the gate is doing I/O it should not.
2. Ports + fakes + SQLite adapters (`MemoryStore`, `CandidateQueueStore`), contract-paired per 13 §2.3.
3. `memory.toml` + its fail-closed loader (D8).
4. The event registration, applier, and payload-sufficiency fixture (D7).
5. The six operations and their schemas (D3), then the wiring.
6. `candidate.expire`'s job (D9), mirroring ADR-047.
7. Documents, CLAIMS, ADR Verification.

## 3. The things most likely to go wrong

- **`Scope.covers` (D2).** A grant of `memory.propose:lesson` does **not** satisfy a bare `memory.propose` request, and a bare grant does not satisfy a qualified request. That is why every proposing principal needs *both* grant shapes. Verify this with a real `PermissionEngine` before you write the grants, not after.
- **EB-004.** The `memory_record` row commits **only inside** `bus.publish`. Copy how `deadline.create`/`project.create` do it; do not commit then publish, and do not publish then commit outside.
- **The record-insert function is shared.** Kang's auto-pass (D4) and `memory.approve` must call the *same* function to create a record. Two insert paths is how a second door gets built by accident.
- **`memory.edit_approve`** lands the edited content as revision 1 of a new record — it does **not** write a `memory_revision` row. Revision history begins when `memory.update` exists (which is not this slice).
- **`memory_revision.device_id`** is `NOT NULL` (ADR-048 Amendment / migration 0021). Nothing in this slice writes that table, but if you find yourself doing so, supply the editing device explicitly.
- **Provenance is schema-enforced and gate-enforced.** Both, deliberately (06 §8.1 + defense in depth). Do not drop the gate check because the CHECK exists.
- **`--strict-markers` and the ADR-050 marker rules** are live. If any test you add is slow enough to want `nightly`, mark it — and know that `tests/suites/architecture/test_ci_marker_coverage.py` governs the marker set.
- **No `.db` anywhere in the repo** (PS-002, tree-hygiene lint).

## 4. Documents (same commit)

- `04_ARCHITECTURE.md` D013 §14.1 — dated correction, `memory.write:{types}` → `memory.propose:{types}` (D1).
- `06_MEMORY.md` §4.2 — dated note: cosine/NLI probes unimplemented, what ships instead, where they arrive (D5). §4.1 — dated note: `rule:`/`plugin:` writers and `private` sensitivity refused until their slices (D6). §12.1 — dated note recording D7's event-log reading.
- `15_EVENT_BUS.md` §6.1 — `memory.saved` joins the taxonomy (D7).
- `12_API.md` §10 — dated note: which of its named operations exist now and which do not (D3).
- `config/defaults/permissions.toml` — `kernel:memory` with `events.publish:kang`; `memory_steward` gains bare `memory.propose`, its three per-type scopes, and `candidates.expire`; `kang` needs nothing (holds `*`).
- `docs/adr/INDEX.md` row; `tests/suites/CLAIMS.md` lines; ADR-051's Verification appended (nothing above it touched).

## 5. Verification protocol

1. `ruff format --check .` first, then `ruff check .`, `lint-imports`, `lint_sizes.py`, `lint_banned_patterns.py`, `lint_tree_hygiene.py`, `lint_doc_citations.py`, `build_root_docs.py --check`.
2. Both non-nightly halves with exact before/after counts. Before: **875** (`tests/unit`+`tests/suites`) and **324** (`tests/integration`).
3. `pytest -m nightly -q` — expected 15 unchanged unless you deliberately marked something.
4. **The exhaustive claim, which is this slice's most important test:** prove that no registered operation can put a non-Kang principal's content into an `active` `memory_record`. Do it by sweeping the operation registry, not by asserting one handler's behavior — 13 §2.8 says "searched exhaustively: no code path".
5. Live-verify against a **throwaway** `%KANG_HOME%` (never the real one; delete it after): a real `build_core()`; a real agent-principal `memory.propose` landing in the queue and **not** in `memory_record`; a real first-party `kang` proposal landing `active` with a real `memory.saved` row in the real event log; a real `memory.approve` promoting a queued candidate under the queue row's own id; a non-first-party session genuinely refused on `memory.approve`; a principal lacking `memory.propose:fact` genuinely refused while one holding it succeeds; `candidate.expire` expiring a backdated row and leaving a fresh one.
6. Never touch the real `%KANG_HOME%` except read-only, and only if you have a reason to.

## 6. Commit

One commit on `main`, local, never pushed, in `git log`'s established style: what changed, what was found, what is proven (with numbers), what is deferred (D10's "named, not decided" list). End with the attribution line your session's system reminder gives you. Do not accept, reopen, or re-decide any ADR. If reality contradicts ADR-051, stop, write down exactly what you found, and ask Kang — especially if the contradiction is anywhere near the gate's admission rules.
