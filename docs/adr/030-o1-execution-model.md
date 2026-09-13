# ADR-030 — O1: the async runtime is not a new decision; DB-001 already made it and M1 skipped it

**Status:** accepted (2026-09-13) — direction only; scope/sequencing of the async migration and whether `http.server` (ADR-009) survives it are explicitly NOT decided here (see "What this ADR does not decide")
**Date:** 2026-08-17
**Supersedes:** none
**Amends:** ADR-028's O1 option table (two of its four options are mis-framed — see Corrections), ADR-019's citation of DB-001 (see Corrections)
**Cites:** 07_DATABASE DB-001 (`docs/07_DATABASE.md:89-112`), `adapters/sqlite/connection.py:6` and `:31`, 12_API API-007 (`docs/12_API.md:101`), ADR-019
**Related:** [[028-m7-foundations.md]] — this discharges its O1

---

## Context

ADR-028 left O1 open: *how does long work run on a single thread, given API-007 forbids blocking long calls?* It framed this as a choice between four mechanisms. **Checking each against code before recommending one showed the framing was wrong: this is not a new decision. 07_DATABASE already made it, scheduled it for M1, and M1 shipped without it.**

DB-001 (`07_DATABASE.md:91-93`) is normative and unambiguous:

> - Exactly **one** write connection, owned by a **single async write-executor task**; all writes flow through it as **queued**, explicit transactions.
> - A **pool (default 4) of read-only connections** (`PRAGMA query_only=ON`) serves all reads.

Its stated purpose is exactly M7's problem (`:107`):

> "WAL gives readers-don't-block-writer, **which is the actual concurrency KANG needs (dashboard reading while a job writes)**."

Its trade-off note even presumes cooperative scheduling (`:111`): *"bulk jobs chunk into ≤1000-row transactions with **yield points**."*

**None of it is built.** `adapters/sqlite/connection.py` opens one plain `sqlite3.connect(str(db_path), isolation_level=None)` (`:31`) — no pool, no `query_only` reader, no queue, no executor task. And the file says so, in its own second line (`:6`):

> "migration tests; **the single-writer executor + read pool arrive at M1.**"

M1 is long past. The deferral was recorded honestly and then quietly expired, because nothing until now needed it: a zero-model, single-user, synchronous Core has no reader that a writer could block. M7 is the first milestone where DB-001's own rationale comes due.

---

## Corrections to the record

Two statements in the existing record are inaccurate and would misdirect whoever builds this.

**1. ADR-028's O1 option "step agent runs on the existing ADR-019 tick" does not solve the stated problem.** `service_actions()` calls `scheduler.tick()` synchronously (`scheduler_wiring.py:264-278`), so a step that makes a model call holds the thread for that call's full duration exactly as a direct call would. Stepping is a *scheduling* mechanism — it answers "when do I resume", not "how do I avoid blocking". It composes with a solution; it is not one.

**2. ADR-019's stated reason for avoiding a second thread cites DB-001 for something DB-001 does not say.** Its wording (`http_binding.py:79`): *"rather than a second thread (which DB-001's thread-confined connection forbids)."* DB-001 contains no thread-affinity requirement — it requires **serialized writes through one connection**, for ordering determinism that sync's change log depends on. The thread confinement is real but is an artifact of the current implementation: `sqlite3.connect` defaults `check_same_thread=True`, so Python enforces it. ADR-019's *conclusion* was right for the code as it stands; its *citation* attributes the constraint to the constitution rather than to a simplification of it. Worth correcting because the difference decides whether async is a deviation or a completion — and it is a completion.

**Third instance found at acceptance review (2026-09-13), not caught when this was drafted:** the identical mis-citation ("DB-001's thread-confined single writer") also appears in `scheduler_wiring.py::_make_ticking_server_class`'s docstring (added by ADR-023, which split scheduler wiring out of `composition.py` after this ADR was already written). Same correction applies; the code comment is fixed in the same commit that accepts this ADR.

---

## Decision (recommended, pending Kang)

**Implement DB-001 as written — async write-executor task plus a read-only connection pool — and treat that as the M7 execution model.** Not as a new architecture choice, but as the delivery of a decision made in 07_DATABASE and deferred past its stated milestone.

Consequences that follow directly, rather than needing their own invention:

- **API-007's "blocking long calls MUST NOT exist" becomes satisfiable** — an agent run awaits its model call while the write-executor and readers keep serving.
- **ADR-019's tick keeps working unchanged in shape**, becoming a scheduled coroutine rather than a `service_actions()` callback. Its actual claim — catch-up runs on a timer, on the connection-owning context — survives.
- **The `invocation` row remains the crash-survivable state** API-007 already requires ("task state persists as `invocation` rows"), so resumption after restart needs no new table.
- **Concurrency caps become real** and ADR-028's C2 is superseded on this point: C2 correctly said "no caps needed" *for a single-threaded runtime*; once DB-001's design lands, the orchestrator's admission limits (05_AGENTS §4) have something to limit. C2's reasoning was sound and its conclusion is now conditional — flagged rather than left to contradict.

### Why not the worker-thread alternative

A thread doing only the model network call, never touching `kang.db`, is genuinely compatible with the code today, and it was my initial recommendation. Rejected on this: it is a *second* concurrency mechanism invented to avoid building the *first* one the constitution already specified. It would leave DB-001's executor and pool unbuilt indefinitely, add a thread-safety boundary nothing else in the system has, and still not give readers-don't-block-writer — the property DB-001 names as "the actual concurrency KANG needs." Choosing it would trade a documented design for an undocumented one to save effort now.

---

## What this ADR does not decide

- **Scope and sequencing of the async migration.** Converting store calls, the bus, the scheduler and the HTTP binding is the largest single change in Phase 1 and needs its own ADR with a real slice plan. This ADR establishes *what* and *why*, not *how*.
- **Whether `http.server` survives it.** ADR-009 ratified stdlib `http.server` for a synchronous Core (D002). An async runtime revisits that, and that is an ADR-009 amendment, not an aside here.
- **`sleeper.py`'s AsyncSleeper.** Already foreseen behind the existing port (`:16-18`) — mechanical once the runtime exists.

## Consequences

- **O1 is discharged as a question about *when*, not *what*.** The architecture was chosen in 07_DATABASE; M7 is where not having it stops being free.
- **A silently-expired deferral is now visible**: `connection.py:6`'s "arrive at M1" promise, unmet since M1, found only because M7 forced the question. Worth a look at whether other in-code milestone promises have expired the same way — not investigated here.
- **Two record corrections land** (ADR-028's option table, ADR-019's DB-001 citation), so the next reader is not misdirected by either.
- **No code changes.** This is a decision about which design to complete.
