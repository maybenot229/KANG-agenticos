# ADR-019 — The continuous scheduler tick loop: `service_actions()` on the existing single-threaded HTTP server

**Status:** accepted
**Date:** 2026-08-10
**Affected documents:** 04_ARCHITECTURE D014 (closes the "jobs execute as supervised tasks" gap for the boot-only case), `src/kang/api/http_binding.py`, `src/kang/kernel/runtime/composition.py`
**Cites:** 11_CODING_STANDARDS §25 (threads outside adapter wrappers, unsupervised tasks, wall-clock outside ports — all forbidden), 07_DATABASE DB-001 (single writer connection, thread-confined), ADR-006 (Part B ruling 4: the composition root is the one module permitted to know both the scheduler and the transport layer)
**Related:** [[006-cron-schedules-and-job-invocation.md]] (named `job.timeout_s` enforcement as needing "the supervised-task machinery," out of scope here too)

---

## Context

`Scheduler.catch_up()` (`src/kang/kernel/scheduler/scheduler.py`) processes every job's missed slots against its catch-up policy, and is idempotent by construction — its baseline is `max(job_run.started)` per job, so calling it again mid-session only picks up newly-due slots. But it is only ever called once, at boot (`composition.py::serve()`), whose own docstring names the gap directly: *"It does not start a continuous tick loop: nothing here re-checks for newly-due jobs while the process keeps running, only at each fresh boot... a separate, larger decision (a supervised background task — 11 §25 bans unsupervised threads, and no such primitive exists in this codebase yet) — deliberately not taken here."*

**The actual obstacle is DB-001, not the absence of a loop.** `kang.db` is opened with `sqlite3.connect()`'s default `check_same_thread=True` (`adapters/sqlite/connection.py`), and `http_binding.py::make_server`'s own docstring says the HTTP server is single-threaded "by design: the kang.db connection is single-writer (DB-001) and thread-confined, so all requests are served in the connection-owning thread." A background thread calling `catch_up()` on a timer would either crash outright (SQLite refuses cross-thread use of a connection opened elsewhere) or require a second write connection — breaking the single-writer invariant DB-001 exists to guarantee. DB-001's *target* design names a queued async write-executor for exactly this kind of concurrent access, but that is explicit M1+ future work (`connection.py`'s own comment); nothing here should informally build a piece of it to solve one caller's problem.

**Scope note, so this ADR doesn't overclaim:** `event:{type}` schedules (`Schedule.is_event_triggered`) are parsed but not wired to any bus subscription anywhere in `src/` today — grepped directly, not assumed. This ADR's tick only re-triggers `catch_up()`, which only ever processes wall-clock/interval occurrences (`occurrences_in`). Event-triggered job admission remains unbuilt and unaffected by this decision.

---

## Options

**A — A background thread with its own write connection / write queue.**

- *For:* the "real" architecture DB-001 eventually wants (a queued async write-executor), built early.
- *Against:* that queue does not exist yet and is explicit future scope (M1+), not this ADR's to invent informally for one caller. Building a general concurrent-write primitive to solve "re-run an idempotent boot step periodically" is disproportionate — real infrastructure risk (write ordering, busy-timeout tuning, crash semantics for a half-drained queue) for a problem that doesn't need concurrent writes at all. **Rejected.**

**B — A background thread that only signals (e.g., sets a `threading.Event`), with the main loop polling it.**

- *For:* keeps DB access on the main thread.
- *Against:* still introduces a bare thread in kernel/composition code — exactly what §25 forbids outside an adapter wrapper — for no benefit over C below, which needs no thread at all. **Rejected.**

**C — `service_actions()` on the existing single-threaded `HTTPServer` (recommended).**

- *For:* `socketserver.BaseServer.serve_forever(poll_interval=...)` already calls `service_actions()` once per poll cycle, on the exact thread that already owns the request loop and the `kang.db` connection — it exists in the stdlib precisely for periodic housekeeping (`ForkingMixIn` uses it for zombie-process reaping). No new thread, no new connection, no new primitive to design or test, no new dependency. `catch_up()`'s existing idempotency is what makes "just call it again periodically" correct by construction rather than a new scheduling algorithm.
- *Against:* ties a scheduling concern to the transport server's lifecycle. Judged acceptable — `serve()` already owns exactly this composition (it calls `catch_up()` once already), and the transport module itself (`http_binding.py`) stays fully scheduler-ignorant (see Decision).

### Decision

Adopt **C**.

1. **`make_server` gains a `server_class: type[HTTPServer] = HTTPServer` parameter.** `http_binding.py` stays pure transport — it still does not import or know about `Scheduler`. This is the only change to that module.
2. **`composition.py::serve()` builds a small `HTTPServer` subclass overriding `service_actions()`** to call `core.scheduler.catch_up()` when at least `TICK_INTERVAL_S` has elapsed since the last tick, timed via `core.clock` (not wall time directly — §25's "wall-clock outside ports" ban applies here same as everywhere else). This is the composition root's role per ADR-006 ruling 4: the one module permitted to bridge layers that must not import each other directly.
3. **`TICK_INTERVAL_S = 60` is a plain constant in `composition.py`**, not a `kang.toml` key. `kang.toml`'s existing tunables (`[planner.triggers]`) are all *lived* trigger times Kang has an actual routine around; tick cadence is an implementation detail of "how promptly does catch-up notice new work," not a decision anyone has asked to make yet. Inventing a config surface for it now would be a tunable nobody asked to tune. Promotable to config later with a two-line change if a real need shows up.
4. **A tick failure is caught, audited, and does not crash the server loop.** Same shape `Scheduler._run_slot` already uses for a failed job body: catch the exception inside the `service_actions()` override, `audit.record("kernel:scheduler", "automation.tick_failed", {"error": f"{type(exc).__name__}: {exc}"})`, let the next tick retry. `automation.tick_failed` extends the existing `automation.*` audit vocabulary (`automation.paused`, `automation.unconfigured`) rather than inventing a new namespace. A tick-level exception is necessarily more serious than a per-job failure — `catch_up()` already isolates those internally — so it more likely indicates something like a DB error; still not grounds to take the whole Core down over what may be transient.
5. **`job.timeout_s` enforcement is explicitly not addressed here**, same as ADR-006 already flagged. A hung job body still hangs whichever tick calls it, boot catch-up or this one — that needs a mechanism for interrupting an in-flight call, which is real, separate work.
6. **No general-purpose supervised-task primitive is introduced.** D006's still-unbuilt promise that event bus handlers "run as a supervised task" would need one; this ADR deliberately does not build that infrastructure for a single caller. If a second caller with a genuine concurrency need shows up, that is a new ADR's decision, not a retrofit of this one.

---

## Consequences

- `serve()` now keeps `core.scheduler` (when configured — it is `None` on missing/invalid `kang.toml`, same fail-closed path as today) live for the process's lifetime instead of running catch-up once at boot.
- `make_server` gains one parameter; no import direction changes, no new dependency, no new port, no new adapter, no new top-level directory.
- New audit action `automation.tick_failed`, consistent with the existing `kernel:scheduler` vocabulary.
- **What gets harder:** the "single instance, single thread, single connection" assumption becomes more load-bearing than before — it was already relied on for correctness (DB-001), and now the live tick depends on it too. A future move toward DB-001's async write-executor or a threaded server must deliberately re-home this tick, not lose it silently.
- **Explicitly out of scope, flagged not guessed:**
  - `job.timeout_s` enforcement (needs interrupting an in-flight call — separate mechanism).
  - Event-triggered job admission (`schedule = 'event:{type}'`) — parsed, unwired, unaffected by this ADR.
  - A general supervised-task primitive for other future callers (e.g. D006's event-bus handler isolation).

## Live verification (2026-08-10)

Unit tests prove the gating logic (`tests/unit/kang/kernel/runtime/test_scheduler_tick.py`) and `Scheduler.tick()`'s failure containment (`tests/unit/kang/kernel/scheduler/test_scheduler.py`) in isolation. The real end-to-end claim — a single continuous, un-restarted process notices a job that becomes due *after* boot — was proven against a real running Core, not just unit tests:

- A throwaway `%KANG_HOME%` (never the real one) was built with `config/kang.toml` setting `morning_plan`'s trigger ~2.5 minutes in the future (UTC, to sidestep timezone conversion) and the shipped default `permissions.toml` copied in unmodified.
- A real `python -m kang.kernel.runtime.composition` process was started and left running continuously — no restart at any point.
- Confirmed via `system.health` that `morning_plan` registered with the expected cron, and via a direct read of the real `job_run` table that it held **zero rows** immediately after boot (boot catch-up correctly found nothing due yet).
- Waited past the trigger time with the process still running. A `job_run` row appeared — `started = '2026-08-10T15:15:00+00:00'` (the exact slot), `outcome = 'ok'`, `finished` timestamped ~43s after the slot — with **no restart between boot and this row appearing**, which is what isolates "the live tick did this" from "boot catch-up did this."
- `system.health` afterward still showed `consecutive_failures: 0`; the audit log held zero `automation.tick_failed` entries — a clean run, not a failure that happened to still produce a row.
- Process stopped, throwaway `%KANG_HOME%` deleted. The real, persistent Core (`%KANG_HOME%` = `C:\Users\meime\kang-home`) was never touched by this verification.
