# ADR-036 — the async migration slice plan: an executor/pool inside `adapters/sqlite/`, not a rewrite

**Status:** accepted (2026-09-13) — sequencing/destination only; each slice's own implementation (D2/D3/D4) is still unbuilt and gets its own review when written
**Date:** 2026-09-13
**Supersedes:** none
**Affected documents:** none yet — this ADR sequences the work; each slice's own implementation is reviewed against it, not re-litigated
**Cites:** ADR-030 (accepted — "scope and sequencing of the async migration… needs its own ADR with a real slice plan. This ADR establishes *what* and *why*, not *how*" — this is that ADR), ADR-035 (accepted — `aiohttp` is the transport this plan wires in), 07_DATABASE DB-001 (`docs/07_DATABASE.md:91-93`), 11_CODING_STANDARDS §12 (`docs/11_CODING_STANDARDS.md:119-121`), `api/dispatch.py` (the `"kind": "command" | "query"` field this plan routes on, already registered for every operation)
**Related:** [[030-o1-execution-model.md]], [[035-operation-channel-transport-after-async.md]] — this is the third and (for now) final document in that chain

---

## Context

ADR-030 named this ADR directly and declined to pre-empt it: *"Scope and sequencing of the async migration… is the largest single change in Phase 1 and needs its own ADR with a real slice plan."* Sizing that plan meant actually counting the surface area rather than guessing at its scale, and reasoning concretely about what SQLite's own nature does and does not force on the design.

### The real numbers

18 real store/adapter files in `adapters/sqlite/`, 19 matching fakes in `adapters/fakes/`, 23 domain port Protocols, 15 operation-handler files, and 85 test files covering 903 tests — all synchronous today, all calling directly into `sqlite3` (which has no async driver; there is no "await-native" way to talk to SQLite in Python, full stop). A naive "convert every store method to `async def`" migration touches all of it in one pass — exactly the kind of undertaking IM-002 warns is "cheapest at 500 lines and ruinous to retrofit at 50,000," except in reverse: this codebase is already past 500 lines, and a full-surface conversion is a genuinely enormous, high-risk cutover with no natural stopping point mid-way.

### The fact that changes the shape of this plan: fine-grained async coloring buys nothing SQLite can use

Because `sqlite3` is blocking C code either way, "convert `TaskStore.create()` to `async def` and `await asyncio.to_thread(conn.execute, …)` inside it" and "keep `TaskStore.create()` exactly as it is, and wrap the *entire request* in one `asyncio.to_thread(...)` call" dispatch the identical blocking call onto the identical kind of worker thread — the granularity differs, the underlying mechanism does not. The difference only matters for code that needs to **interleave** a store write with something else genuinely async and long-running *in the middle of one logical operation* — write an `invocation` row, *then* `await` a multi-second model call, *then* write again, without holding a worker thread hostage for the model call's whole duration. **That case exists exactly once in this system's declared future: M7's agent runtime** (API-007's own "an agent run awaits its model call while the write-executor and readers keep serving," ADR-030's own consequence). None of the 18 stores or 15 handlers built so far do this or are expected to — every existing operation is admit-validate-write-return, start to finish, with no await-worthy gap in the middle.

### A design fact that resolves the natural next question for free: the registry already carries the exact routing signal needed

Every operation is already registered `"kind": "command"` or `"kind": "query"` (`_op(...)`, present since M4). Commands write; queries don't (`api/dispatch.py`'s own idempotency-key gate already keys off this same field). This is precisely the distinction DB-001 needs to route work — no new registry field, no new per-operation declaration, no risk of an operation being silently mis-routed by an author forgetting to flag it.

### The thread-affinity trap a naive read of "just wrap it in `to_thread`" walks into

`sqlite3.connect()` defaults `check_same_thread=True` — a connection raises if used from a thread other than the one that created it. `asyncio.to_thread()` dispatches onto a shared, general-purpose thread pool; consecutive calls are **not** guaranteed the same worker thread. Wrapping DB-001's *single write connection* in bare `to_thread()` calls would intermittently raise, not just underperform. The fix DB-001 already specifies is the fix for this too: **one connection, owned by one dedicated worker**, not a generic pool — for the read side, DB-001's own "pool (default 4)" reads the same way: four *dedicated* read-only connections, each pinned to its own worker, not four arbitrary threads sharing four connections.

---

## Decision

### D1 — Scope: build a bounded connection executor/pool inside `adapters/sqlite/`; do NOT convert the 18 stores or 15 handlers to `async def`

This is the central call this ADR makes, and it is a real recommendation, not a punt (unlike O1's original four-way table) — the facts above point at one answer:

- The write path becomes a **write-executor**: one dedicated worker thread, created once, owning the sole write connection for its entire life (naturally satisfying `check_same_thread=True` — it never leaves that thread). Work arrives as queued callables; the executor runs them one at a time, in arrival order — DB-001's own words ("queued, explicit transactions"), not a new design.
- The read path becomes a **read pool**: four dedicated worker threads, each opening and permanently owning one `PRAGMA query_only=ON` connection. A read request checks out an idle worker (a bounded semaphore of 4), submits, releases it back.
- **Every store's own SQL and business logic is unchanged, on both paths. Command-handler construction is unchanged. Query-handler construction is not** — see D4, which is where this asymmetry actually lives; it is real, not glossed over here. A "command" operation's entire handler invocation — the handler function, whatever store calls it makes, whatever it publishes on the bus — is submitted as *one atomic unit of work* to the write-executor, using the same store instance built once at boot, exactly as today. A "query" operation's handler invocation is submitted to the read pool, but genuinely using all four read connections (rather than one, permanently, by accident) requires the query handler's store to be bound *per call*, not at boot — D4 spells out why and what that costs.
- Built **inside `adapters/sqlite/`** specifically (not the composition root, not `api/`) so the thread usage is textbook-compliant with 11_CODING §12's own wording — "no threads except inside adapters that must wrap blocking libraries (and then: `to_thread`, bounded [5, fixed], documented)" — without needing an interpretive stretch of what "adapters" means.

**Why not the full conversion.** It would touch all 18 stores, 19 fakes, 15 handlers, and a meaningful fraction of 903 tests, for a benefit fine-grained coloring cannot actually deliver on top of SQLite (see Context) — cost without the payoff. If a real need for finer-grained interleaving is ever found *outside* the agent-runtime case D5 already carves out, that is itself a new, specific finding deserving its own ADR at that time — not a reason to pre-pay for it now.

### D2 — Slice 0: the kernel's supervised-task primitives (prerequisite, blocks D4). **DONE (2026-09-13).**

11_CODING §12: *"All concurrency passes through the kernel's supervised-task primitives (timeout, cancellation, naming) — bare `create_task` outside the kernel is lint-banned."* Neither the primitive nor the lint rule exists (`tools/lint_banned_patterns.py` has no `create_task` check today). Both land together, matching this project's own pairing discipline (a rule ships with its enforcement) — the scheduler's own tick task (D4) is the first real caller. Exact API design is that slice's own work, not this ADR's ("what, not how," matching ADR-030's own discipline).

Landed as `kernel/runtime/supervised_task.py::create_supervised_task` — mandatory `name`, an optional `timeout_s` enforced via real `asyncio.wait_for` cancellation (not `Job.timeout_s`'s post-hoc reporting), and a done-callback that logs any unhandled exception loudly (DB-P7), excluding deliberate cancellation. Zero callers yet, as intended — D4 remains the first real one. `tools/lint_banned_patterns.py` gained the matching rule.

### D3 — Slice 1: the write-executor and read-pool themselves. **DONE (2026-09-13).**

Built and unit-tested in complete isolation inside `adapters/sqlite/`, with **zero existing callers** — nothing outside this slice changes, nothing outside this slice's own new tests can break. This is the lowest-risk possible first real slice: it can be reviewed, merged, and left dormant if D4 needs to slip.

Landed as `adapters/sqlite/connection_pool.py::WriteExecutor`/`ReadPool`, plus a new `open_read_only_connection` alongside `connection.py`'s existing `open_connection` (the same PRAGMA discipline, `query_only = ON`, verified not just set). Both classes are built on `concurrent.futures.ThreadPoolExecutor` — the same underlying mechanism `asyncio.to_thread()` itself uses, but with a purpose-built, fixed-size pool (1 worker for writes, 4 for reads) instead of the ambient shared one, so a connection opened by a given worker is only ever touched by that same worker again, satisfying `check_same_thread=True` by construction rather than by discipline. `ReadPool` uses `ThreadPoolExecutor`'s `initializer` hook so each of its workers opens and permanently owns exactly one connection. Proven, not assumed: submissions to the write executor run in strict arrival order even when issued concurrently; concurrent read submissions genuinely land on more than one connection (four 50ms jobs complete in well under their serial sum); a write attempted through a pool connection raises loudly.

### D4 — Slice 2: `aiohttp` wiring (ADR-035) + routing "command"/"query" through Slice 1

- `http_binding.py` is rewritten against `aiohttp`, per ADR-035.
- `Dispatcher` gains one new async entry point. Its body is unchanged in substance — it reads `entry["kind"]` (already there) and submits the existing `_run(...)` call to the write-executor (`command`) or read-pool (`query`) from D3, `await`-ing the result.
- The scheduler's tick (ADR-019) becomes a native `asyncio` periodic task, created through D2's supervised-task primitive, submitting its own job-triggered dispatch calls through the identical D3 routing — a scheduled job is a command like any other.
- **This is the slice where the system's actual runtime behavior changes**: a slow write (or a slow scheduled job) no longer blocks a concurrent read — DB-001's stated goal, and ADR-035 Context finding #4's already-existing gap, both close here.

**Found at review (2026-09-13), not caught while drafting: this slice is not purely a `Dispatcher`/`http_binding.py` change — it also changes how query-kind handlers are built.** Every handler today is constructed exactly once, at boot (`_build_handlers()`), closed over a store instance permanently bound to the one write connection. That is fine, unchanged, for command handlers under D3's routing — they keep using that same boot-time instance, submitted as a whole to the write-executor, exactly as D1 claims.

It is *not* fine, unexamined, for query handlers. A handler closed over one store instance is closed over one connection, forever. If a query handler built once at boot is wired to (say) read-connection #1, every call to it uses connection #1 — the other three sit idle regardless of concurrent load, and DB-001's actual goal (four readers able to proceed independently) is not delivered; only the *appearance* of a pool would exist. Genuinely using all four requires the query handler's store to be **constructed per call**, against whichever connection the pool currently checks out — a real, if narrow and mechanical, change to the handler-factory pattern for the query half of the registry specifically. Command handlers, and the handler-factory pattern for them, are unaffected. This is Slice 2's own implementation detail ("how," not redesigned here), but it is real cost this ADR should not understate: expect every query-kind handler's wiring in `_build_handlers()` (a meaningful fraction of the 15 handler files) to change shape, even though the handler *functions themselves* and the stores' own SQL do not.

### D5 — Explicitly separate, and NOT scheduled by this ADR: the M7 orchestrator/agent runtime

Written **natively async from first line** — new code, no existing tests to protect, no reason to route it through D3's per-request executor submission. It runs directly on the shared event loop as its own supervised task (D2), calling the write-executor/read-pool as first-class async collaborators for its own reads/writes, so an in-flight model-call `await` never occupies a D3 worker thread. This is the one case D1 carved out; ADR-028's own sequencing (model router, budget ledger, executor, degradation ladder — each its own ADR) still governs its order, unchanged by this document.

### D6 — What this ADR does not decide

- **Whether any of today's 18 stores or 15 handlers ever gain real `async def` coloring.** Named answer: very likely never, on the reasoning in Context — but not foreclosed. **Trigger, if this is ever revisited:** a single existing command needs to interleave a store write with an in-flight, multi-second external `await` mid-handler — structurally the same shape as the agent-runtime case D5 already owns, which is exactly why this trigger is not expected to fire for the *existing* surface.
- **The write-executor/read-pool's exact API** (queue shape, `Future`/coroutine return type, timeout/cancellation wiring through D2's primitive) — D3's own implementation, not designed here.
- **The event channel's own binding** — `aiohttp`'s WebSocket support (ADR-035) makes it cheap whenever built; still unscoped, still unbuilt.
- **Any change to the 18 stores' own tests, or to command-handler tests.** D1's whole point is that none are required there. Query-handler tests are a narrower exception, not a silent gap: D4's own found cost (per-call construction) means query-handler unit tests exercise a different construction path than they do today, so their *setup* changes even though the handler's *behavior* and the store's own tests do not. D2's and D3's new code gets new tests; D4's tests cover the routing seam, the query-handler construction change, and the `aiohttp` binding itself.

---

## Consequences

- **The migration ADR-030 called "the largest single change in Phase 1" becomes three small, independently-mergeable slices** (D2, D3, D4) instead of one undifferentiated rewrite — each individually low-risk, each leaving the system green if the next one slips.
- **The 18 stores' own SQL, business logic, and public method signatures are untouched — on both the command and query paths.** What is *not* untouched: query-kind handlers' wiring in `_build_handlers()` moves from once-at-boot to per-call construction (D4) — a real, narrow, mechanical change, not zero-cost, named explicitly rather than folded into a blanket "unchanged" claim. Command handlers, the 19 fakes, and the ~900 existing tests are genuinely unaffected. Stated plainly so a future session does not "finish the job" by converting the stores themselves without a new, specific reason (the same discipline ADR-029 D4 used for the UI's "task card" label) — nor mistakes the query-handler wiring change for something it isn't.
- **DB-001 is delivered as literally written** (one write connection, one executor, a four-connection read pool, queued writes) — not reinterpreted, not partially implemented.
- **A new lint rule lands with Slice 0**, closing the "bare `create_task` outside the kernel" gap 11_CODING §12 has named since before any of this was built.
- **M7's agent runtime is unblocked to be written natively async**, per its own future ADRs, without waiting on or being shaped by a store-layer rewrite that (per D1) never happens.
