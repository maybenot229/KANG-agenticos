# ADR-035 — the operation channel's transport after ADR-030: `http.server` does not survive

**Status:** accepted (2026-09-13) — destination only; scope/sequencing of the migration remains fully open (see "What this ADR does NOT decide")
**Date:** 2026-09-13
**Supersedes:** none
**Amends:** ADR-009 Part A (`http.server` ratification — operation-channel scope only; Part B, schema authority, is unaffected), 04_ARCHITECTURE D002 (delivers "asyncio throughout," rather than deciding it fresh), 17_PROJECT_STRUCTURE §4.1's legality-matrix row for `api/` (`docs/17_PROJECT_STRUCTURE.md:233`)
**Cites:** ADR-030 (accepted 2026-09-13 — DB-001's async delivery, which forces this question and explicitly deferred it here), 04_ARCHITECTURE D002 (`docs/04_ARCHITECTURE.md:130`), 11_CODING_STANDARDS §12 (`docs/11_CODING_STANDARDS.md:119-121`), E10 (`docs/01_PRINCIPLES.md:283`), ADR-011 (the precedent for rejecting a hand-rolled reimplementation of a solved problem), `aiohttp`'s maintenance checked live at review time (2026-09-13) — release 3.14.3 (July 2026), active issue traffic into August 2026 ([releases](https://github.com/aio-libs/aiohttp/releases), [PyPI](https://pypi.org/project/aiohttp/))
**Related:** [[009-http-transport-and-schema-authority.md]] — this is the reopening its own Tripwire named; [[030-o1-execution-model.md]] — this ADR resolves the one item ADR-030 explicitly deferred ("whether `http.server` survives it")

---

## Context

ADR-030 (accepted this session) commits M7's execution model to completing DB-001's async write-executor + read-connection pool. It explicitly declined to answer one question: *"Whether `http.server` survives it… is an ADR-009 amendment, not an aside here."* This is that amendment.

**Investigating what "surviving" would require turned up the same pattern ADR-029 and ADR-030 each already found: this is not a fresh judgment call. Two already-normative, already-written, never-built decisions answer it directly.**

### 1. D002 itself already says "asyncio throughout" — and ADR-009 deliberately left that clause standing

`04_ARCHITECTURE.md:130`: *"**Core:** Python 3.12+, `asyncio` throughout, stdlib `http.server` serving a localhost-only API…"* ADR-009's own Decision (Part A) is explicit that it did not touch this: *"`asyncio` remains accurate elsewhere in D002 and is unaffected — Python's async runtime, not the HTTP framework, is the D002 clause in question."* So D002's asyncio clause has been standing, untouched, and unimplemented since before ADR-009 was even filed (2026-07-31) — the exact "recorded honestly, then quietly expired because nothing needed it yet" shape ADR-030 found for DB-001, one document up.

### 2. 11_CODING_STANDARDS §12 already specifies the whole concurrency model, in full, and none of it exists

This is not an offhand mention (unlike D010's Pydantic clause, which ADR-009 itself found to be aspirational text with no implementation behind it — this is a different situation, checked separately rather than assumed to be the same). §12, verbatim:

> "`asyncio` single-loop in the core; **no threads except** inside adapters that must wrap blocking libraries (and then: `to_thread`, bounded, documented). No multiprocessing in-core (sidecars are the process story, D001). All concurrency passes through the kernel's supervised-task primitives (timeout, cancellation, naming) — bare `create_task` outside the kernel is lint-banned… Shared mutable state between tasks MUST NOT exist outside the store layer; coordination is by queue/event, not by lock."

Verified against real code: zero concurrency primitives exist anywhere in `src/` (ADR-028 C2's own finding, still true — no `threading`, `asyncio`, `queue`, `async def`, or `await`). No "kernel supervised-task" module exists either — the phrase appears in five documents' prose and nowhere in `src/`. This paragraph is a coherent, load-bearing design, not aspirational filler; it just has never been built.

### 3. §12's rule rules out an entire category of options before this ADR even opens one

*"No threads except inside adapters that must wrap blocking libraries (and then: `to_thread`, bounded, documented)"* forecloses any design that keeps `http.server` alive by giving it its own thread, or by splitting HTTP handling across a thread pool (stdlib's own `socketserver.ThreadingMixIn`/`ThreadingHTTPServer` included). `http.server`'s `serve_forever()` is an **indefinitely-running** blocking call — it cannot be wrapped in `asyncio.to_thread()` (built for *bounded*, one-off blocking operations, explicitly named as such in §12) without either permanently occupying an undocumented, unbounded thread (violating the rule's own words) or defeating "single-loop in the core" outright. Once §12 is taken at face value — and nothing here suggests it is stale or unreasoned the way D010's mention turned out to be — `http.server`'s own execution model is structurally incompatible with the constitution's already-standing concurrency rule, independently of DB-001.

### 4. A fact worth surfacing on its own merits, not just as a consequence of the above: `http.server` already fully serializes, today

`socketserver.BaseServer.serve_forever()` — what `HTTPServer` runs unmodified — calls `service_actions()` and handles one request at a time, sequentially, on one thread. A slow scheduled job (`service_actions()` → `scheduler.tick()`, ADR-019) already blocks every new HTTP connection for its full duration, and a slow HTTP request blocks the next tick. DB-001's own stated concurrency goal — *"dashboard reading while a job writes"* — is not a future M7 problem being pre-empted here; **it is already unmet today**, quietly, because every job built so far is fast, synchronous SQL with no network or model call in it. The same "nothing until now needed it" shape ADR-030 named for DB-001 applies one layer up, to the server that hosts it.

---

## Decision

### D1 — The operation channel's transport is no longer stdlib `http.server`

Given §12 rules out thread-based servers, and hand-rolling HTTP/1.1 parsing over raw `asyncio.start_server()` is the same "reinvents a solved, non-trivial problem" trap ADR-011 already named and rejected for JSON-Schema parsing (chunked transfer encoding, keep-alive, header edge cases — a real, exercised spec, not a toy), the real choice is which asyncio-native library replaces it.

**Recommended: `aiohttp`.**

| Option | Assessment |
|---|---|
| **`aiohttp` (recommended)** | A single, mature, single-purpose asyncio HTTP library — not a framework. Its server component implements exactly what's needed (`POST /op`, one route, dispatching into the existing `Dispatcher`) without route-decorator/schema machinery that would recreate FastAPI's rejected coupling risk (ADR-009 Part A2: schema authorship must not depend on transport features, API-002). Native WebSocket support, at no extra cost, **opportunistically discharges ADR-009's own Tripwire** — the event channel (12_API §6, still unbuilt, still deferred) can bind to the same library later without a second transport decision. One new runtime dependency, joining `tzdata`/`pydantic`. |
| **ASGI (Starlette + an ASGI server, e.g. `uvicorn`)** | Rejected on the same grounds ADR-009 rejected FastAPI: a single `POST /op` route does not exercise routing, middleware, or dependency injection — the actual value an ASGI framework sells. It also means **two** new dependencies (framework + server) for what `aiohttp` does with one. |
| **Hand-rolled `asyncio.start_server()` + custom HTTP/1.1 parsing** | Zero new dependencies, but reinvents a solved, genuinely non-trivial spec by hand — the exact failure mode ADR-011 rejected for a much smaller spec (JSON Schema) than full HTTP/1.1. A silently-wrong edge case here (a malformed `Content-Length`, a keep-alive bug) is worse than the dependency it avoids. **Rejected**, same reasoning as ADR-011 Option B, applied to a harder problem. |
| **Keep `http.server` on the main thread; bridge into a single dedicated background thread hosting the write-executor + read-pool** (each handler calls `asyncio.run_coroutine_threadsafe(...).result()`) | The most tempting option, because it looks like the smallest change — no library swap, `http.server` untouched. **Rejected**, for a reason less obvious than the others: a permanent, unbounded thread whose entire job is hosting the concurrency model is not "inside an adapter wrapping a blocking library" (§12's own exception) — it is a second, parallel execution context that exists for the Core's whole lifetime, which is exactly what "asyncio single-loop in the core" forbids, just less visibly than `ThreadingHTTPServer` does. It also does not fix Context finding #4: `http.server` still handles one connection at a time, so it moves *where* write-serialization happens without solving the part that actually matters — a dashboard read still queues behind whatever the one HTTP thread is doing, model call or not. |

### D2 — What this ADR does NOT decide

Scoped tightly to the transport question, matching ADR-030's own discipline of separating *what* from *how*:

- **DB-001's write-executor + read-pool's actual implementation** (queue shape, pool sizing, `to_thread` wrapping of `sqlite3`) — ADR-030's own "needs its own ADR with a real slice plan" applies here unchanged. This ADR does not design it.
- **The kernel's supervised-task primitives** §12 requires for all concurrency (timeout, cancellation, naming) — named here as a real prerequisite this migration needs, not designed here. Every `create_task` this migration adds is lint-banned outside the kernel until this exists.
- **The event channel's own binding ADR.** `aiohttp`'s WebSocket support makes that binding cheaper *whenever it is built*; it does not pull the event channel's own scope into this ADR. 12_API §6 remains unbuilt and unscheduled by this decision.
- **Migration sequencing** — converting `http_binding.py`, the store layer's connection access, the scheduler tick, and the dispatcher to run on the new loop is the same "largest single change in Phase 1" ADR-030 already named. This ADR picks the destination; it does not lay the road.

---

## Consequences

- **A second, independently-justified runtime dependency lands**, per E10's own test (`01_PRINCIPLES.md:283`: "a new technology earns its place with a written justification") — `aiohttp`, alongside `pydantic`/`tzdata`.
- **04_ARCHITECTURE.md D002** is corrected to note its own "asyncio throughout" clause is now scheduled for delivery (this ADR + ADR-030 + the still-unwritten slice-plan ADR), not merely asserted.
- **17_PROJECT_STRUCTURE.md's legality matrix** (`:233`) is updated: the `api/` layer's transport dependency becomes `aiohttp`, replacing the `http.server` row ADR-009 itself corrected in.
- **ADR-009 Part A is amended, not reversed** — its schema-authority ruling (Part B, Pydantic) is untouched; its Tripwire is the mechanism that predicted and authorizes this exact reopening.
- **What this closes:** the last of ADR-030's own named unknowns ("whether `http.server` survives it") — answered: no.
- **What remains fully open:** every "how" question D2 names above. **No code changes land with this ADR.** It is a destination decision, matching ADR-030's own "decision about which design to complete," one document further down the same chain.
