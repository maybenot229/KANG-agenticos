# ADR-028 — M7 foundations: the four constraints the code imposes, the `task` collision, and the one fork that needs Kang

**Status:** proposed
**Date:** 2026-08-17
**Supersedes:** none
**Affected documents:** none yet — this ADR settles constraints and sequences the work; each numbered slice below gets its own ADR before any code
**Cites:** 12_API API-007 (`docs/12_API.md:99-103`), 05_AGENTS §8 (`:210`), AG-005 (`:224`), 15_EVENT_BUS §6.1 (`:180`), ADR-019 (the single-threaded tick), ADR-006 ruling 4 (jobs dispatch through the normal pipeline), ADR-027 D3 (the executor constraint)
**Related:** the 2026-08-17 M7 read-only investigation (Q1–Q4), which grounds every claim here

---

## Context

M7 — model router, budget ledger, orchestrator, agent runtime, basic chat — is the last unbuilt Phase 1 milestone. It is also the first milestone whose components already exist as empty stubs with declared constitutional homes: `kernel/router/__init__.py` ("Model router, TaskSpec mapping, budget ledger", D010) and `kernel/orchestrator/__init__.py` ("Agent admission, pipelines, budgets", AG-001), both with `__all__: list[str] = []`.

A read-only investigation (2026-08-17) answered four grounding questions against real code. **This ADR does not re-derive those answers; it converts them into binding constraints and names what is still open.** It deliberately decides less than it could: one fork is genuinely Kang's, and pre-empting it in an ADR he has not read would be the failure mode this project's own protocol exists to prevent.

---

## Decision

### C1 — The response envelope is additive; `degraded` is cheap. **Settled.**

There is no envelope type. The success envelope is a dict literal built at exactly one site (`api/dispatch.py:215-219`), serialized verbatim by `json.dumps` (`api/http_binding.py:57-64`), and never schema-validated — `response_schema` is registered but has no enforcement path (its only consumer is `registry.get`'s snapshot). Adding `degraded: bool` is a one-line change that no operation's contract has to absorb, and it round-trips the idempotency cache intact.

**Two obligations M7 inherits with it**, both currently declared-but-unwritten:
- `degraded_result` is in the closed error-code enum (`api/errors.py:29`) and has **never been raised**. 12_API:93 calls it "success-with-marker, not an error — see below", and there is no "see below" in that document. M7's degradation ladder (05_AGENTS §10) is the first thing that will raise it, and the ADR that does so **must also write the missing normative paragraph** — a dangling forward-reference is not a spec.
- `INVOCATION_OUTCOMES` declares `("ok", "failed", "degraded", "denied")` (`domain/ports/invocation.py:26`), but `_finish` is only ever called with `"ok"` or `"failed"` (`dispatch.py:212`, `:214`). M7 is the first writer of the other two. `denied` in particular pairs with 05_AGENTS §8's denial-spike quarantine.

### C2 — Concurrency limits are out of scope. **Settled, and this removes work.**

Zero concurrency primitives exist anywhere in `src/`: no `threading`, `asyncio`, `queue`, `ThreadingHTTPServer`, `async def`, or `await`. The server is plain `HTTPServer` (`http_binding.py:67-68`), one `serve_forever` (`composition.py:618`), and ADR-019's tick runs `service_actions()` **on the same thread that owns `kang.db`** (`scheduler_wiring.py:251-263`). Two operations cannot execute simultaneously.

**Therefore the orchestrator ships with no concurrency caps, no semaphores, and no parallelism budget.** 05_AGENTS §4's "admission, bookkeeping, and dispatch only" is satisfiable without them today. When O1 (below) is decided, whatever concurrency it introduces brings its caps *with it*, justified by the mechanism that made them necessary — not pre-built against a hypothetical.

### C3 — Cost is new vocabulary, and the gap is already named. **Settled as scope, not as design.**

`_op(...)` produces 11 fields (`api/registry/__init__.py:189-202`); none concerns time, tokens, money, or quota. `budget_exhausted` exists as an error code and is never raised. `Job.timeout_s` is scheduler-only and explicitly post-hoc reporting, not enforcement (`scheduler.py:173-182`).

The gap is not an oversight — it is recorded: `api/schemas/invocation.py:14-18` states *"No `cost` field either: M4/M5 are zero-model by construction (no model calls exist to cost)… not silently invented here as zeros"*, and 09_UI §12 already promises "outcome badges, durations, **costs**" in the Invocations view. **M7 is where that promise comes due**, and the budget ledger is its home (`kernel/router/`'s own declared purpose).

### C4 — Agent principals must not reach the dispatcher unmediated. **Settled by ADR-027 D3.**

Recorded there and restated here because it constrains M7's first structural choice: ADR-006 ruling 4 made jobs dispatch through the ordinary pipeline under a minted session, which is correct for jobs (a fixed three-entry `JOB_OPERATIONS` table). AG-005 (`05_AGENTS.md:224`) is stricter for agents — *"Every agent definition MUST enumerate its allowed tools. There is no 'all tools' grant, no default toolset, and no runtime tool discovery."*

**M7's tool executor MUST enforce the per-agent allowlist itself**, before and independently of the dispatcher's scope check. Minting an `agent:{id}` session and letting it post arbitrary operations to `/op` satisfies neither AG-005 nor SEC-004's "checked at the executor". ADR-027 made the dispatcher a correct *second* layer; it did not remove the executor's obligation to be the first.

Also settled by the same investigation, so M7 does not rediscover them: grants are **boot-time only** — the engine snapshot is immutable for its lifetime (`engine.py:45-52`) and no `grant.modify` operation exists — so every agent principal must be declared in `permissions.toml` before it can hold anything. And an ungranted principal already fails cleanly (`permission_denied`, `engine.py:56-62`), so no new denial machinery is needed, only the denial-*rate* tracking 05_AGENTS §8 requires for quarantine.

---

### V1 — The `task` vocabulary collision must be resolved before `agent.invoke` is registered

**This is the finding most likely to cause silent damage, because both sides are already written down.**

`task.*` currently means **a TODO item**: `task.create` / `task.get` / `task.complete` are registered against `TaskStore`, scoped `task.read` / `task.write`.

API-007 (`12_API.md:101`) uses the same word for **an async work handle**: *"command → returns `task_id` immediately → progress/output via the event channel (`task.updated`, streamed chunks) → outcome as a queryable task resource."* `:103` adds *"cancellability (AG-007: cancel is `task.cancel`)"* and *"task state persists as `invocation` rows"*. `:153` then lists `task.create` and `task.cancel` side by side in one illustrative command list, as though they were one family. They are not: `task.create` makes a TODO, `task.cancel` would abort an agent run.

The constitution is already half-aware of this. 15_EVENT_BUS §6.1 (`:180`) annotates the Lifecycle example as `task.updated` **"(API long-running tasks)"** — an inline disambiguation that exists precisely because the bare name is ambiguous. That annotation is a symptom, not a fix.

**Recommendation (not yet a decision — it touches 12_API's normative text):** M7 should not register `task.updated` / `task.cancel` / any `task_id`-returning operation under the `task.*` namespace. The async-work resource is already `invocation` in code and in 12_API's own sentence ("task state persists as `invocation` rows") — so `invocation.cancel` and an `invocation.*` event family fit the existing vocabulary without inventing a synonym. That keeps CLAUDE.md §5's rule intact ("one concept, one name") in the direction that matters: the collision here is two concepts under one name, which is the same defect inverted and harder to see.

This needs its own ADR because it amends 12_API's normative wording. **It must land before any M7 operation is registered**, since the first registration sets the precedent.

---

### O1 — OPEN, and genuinely Kang's: how does long work run on a single thread?

The one fork this ADR will not pre-empt. Two normative facts collide:

- **API-007 (`12_API.md:101`), normative:** *"Blocking long calls MUST NOT exist."*
- **The runtime, verified:** one thread, no async, and a blocking `time.sleep` sleeper (`sleeper.py:29-31`). A synchronous model call would freeze HTTP serving *and* the ADR-019 scheduler tick for its full duration.

The options, with the code fact that bears on each — presented for Kang's decision, not ranked, because each trades a different constitutional value:

| Option | The code fact that matters |
|---|---|
| **asyncio runtime** | `sleeper.py:16-18` already anticipates it — *"when an asyncio runtime lands… an AsyncSleeper joins behind the same port"* — and notes 04_ARCHITECTURE has **no decision number** for async (a stale-citation correction made 2026-08-09). So it is foreseen but undecided, and it is the largest change: every store call sits on a thread-confined connection (DB-001). |
| **Worker thread for model calls only** | DB-001's connection is thread-confined; a worker that never touches `kang.db` and hands results back to the owning thread respects that, but ADR-019's whole rationale was avoiding a second thread. |
| **Step agent runs on the existing tick** | Reuses ADR-019's `service_actions()` hook with zero new primitives — the most in-grain option — but a model call is seconds long, so a run must be *resumable between ticks* rather than executed within one, which pushes state into the `invocation` row. |
| **Subprocess per run** | `scheduler.py:14`/`:177` already describes this shape for job timeouts and rules it *not ripe* — "a killable subprocess and its own IPC design". Solves timeout enforcement (AG-007 cancel) as a side effect; adds an IPC surface. |

**Recommendation on process, not on choice:** this is the same class of decision as ADR-019 and the retry-with-backoff conversation — both were resolved by a real design conversation before code, and both produced better answers than a unilateral ADR would have. O1 should get that treatment. **Everything else in M7 is downstream of it**, which is why this ADR stops here rather than sequencing implementation slices that O1 could invalidate.

---

## Sequencing

1. **V1** — resolve the `task`/`invocation` collision (amends 12_API). Blocks every M7 registration.
2. **O1** — decide the execution model with Kang. Blocks the orchestrator and agent runtime.
3. Then, in any order: model router + `TaskSpec` mapping (D010) · budget ledger (C3) · agent registry + manifest assembly · the executor with AG-005's allowlist (C4) · degradation ladder + the missing `degraded_result` paragraph (C1) · chat as API-007's streaming case.

## Consequences

- **Two pieces of M7 scope are removed before they are built:** concurrency caps (C2) and any bespoke denial machinery (C4).
- **Two latent contradictions are surfaced with owners:** the `task` collision (V1) and `degraded_result`'s dangling "see below" (C1).
- **No code changes.** This ADR is constraints and sequencing; it deliberately registers nothing, since V1 must settle the namespace first.
- **What this ADR does not claim:** any position on O1. It presents four options with their code consequences and stops.
