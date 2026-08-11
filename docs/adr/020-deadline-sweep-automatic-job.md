# ADR-020 — Wire `deadline.sweep` as an automatic job

**Status:** accepted
**Date:** 2026-08-11
**Affected documents:** `config/defaults/permissions.toml` (`kernel:scheduler`'s grant), `src/kang/kernel/runtime/composition.py` (`JOB_OPERATIONS`, `_wire_scheduler`)
**Cites:** ADR-006 (Part B — the job→operation dispatch mechanism this reuses verbatim; Consequences explicitly named this exact gap: "wiring `deadline.sweep` as a second real job... would need a new `kernel:scheduler` scope grant, an authority-path change requiring its own ADR"), 05_AGENTS Appendix E (`deadline_sweep | hourly | any | run_once_latest` — the cadence/catch-up policy, already decided, not re-litigated here), CLAUDE.md §4 (permission-grant changes require an ADR)
**Related:** [[019-scheduler-tick-loop.md]] (the live tick this job now actually benefits from — without it, an hourly job registered mid-session would only ever run at the next boot)

---

## Context

`deadline.sweep` (FR-031: lead-time alerts, `tracked → alerted` transitions) has existed and been fully tested since M3, but is only ever invoked manually — through the operation channel directly (tests, curl, a future UI action), never on a schedule. `morning_plan` is the only job the Core has ever registered.

Nothing here is a fresh design call. ADR-006 Part B already decided the entire mechanism a job uses to invoke an operation (dispatch through the normal pipeline, under `kernel:scheduler`, `first_party=False`, idempotency keyed on `(job.id, slot)`), and 05_AGENTS Appendix E already specifies this job's own cadence: `hourly`, product state `any` (unlike `morning_plan`'s wake-boundary anchoring, a sweep must run regardless of what Kang is doing), catch-up `run_once_latest` (checking currently-active deadlines against *now* is idempotent with respect to missed intervals — running once after downtime catches everything a missed hourly run would have, so replaying every missed slot would just recompute the same result `N` times for no benefit).

**The one real trigger:** `deadline.sweep`'s registered scope is `deadlines.mark_alerted` ([registry/__init__.py:279](../../src/kang/api/registry/__init__.py)); `kernel:scheduler`'s grant in `permissions.toml` currently holds only `tasks.write`. Adding a scope to a principal is an authority-path change (CLAUDE.md §4), which is what makes this a small ADR rather than a plain commit — not any uncertainty about the job's shape.

**Confirmed, not assumed:** `deadline.sweep`'s registry entry does not set `first_party_only` (defaults to `False`), so the scheduler's non-first-party session can call it — same as `plan.generate` already does for `morning_plan`.

---

## Decision

Wire `deadline_sweep` exactly as `morning_plan` is wired, with nothing new invented:

1. **`permissions.toml`:** `"kernel:scheduler" = ["tasks.write", "deadlines.mark_alerted"]` — the one line that answers "what can automation trigger?" (already true for `tasks.write`; this ADR is the reviewable record of the addition, same as ADR-006's own Consequences promised).
2. **`composition.py::JOB_OPERATIONS`:** add `"deadline_sweep": "deadline.sweep"` — the plain, greppable literal ADR-006 ruling 4 already established as the one place this mapping lives.
3. **`composition.py::_wire_scheduler`:** register a second `Job` alongside `morning_plan` — `id="deadline_sweep"`, `name="deadline_sweep"`, `schedule="hourly"` (the existing interval grammar; no cron adapter involved, and per ADR-006's own reasoning, a sweep's exact minute is meaningless — anchor-relative is correct, not a workaround), `catch_up="run_once_latest"`. Unconditional on any `kang.toml` value beyond the config loading successfully at all — `deadline_sweep`'s cadence is fixed, not a Kang-tunable trigger time like `[planner.triggers]`, so no new config key is added.
4. Both jobs share one `Scheduler` instance, one boot catch-up, and — since ADR-019 landed first — one live tick. No new scheduler mechanism; `_catch_up_job`/`tick()` already iterate `job_store.list_jobs()`, so a second registered job is handled for free.

### What stays explicitly out of scope

- **`job.timeout_s`/retry-with-backoff enforcement.** 05 Appendix E lists "2m timeout, 2 retries" for `deadline_sweep`; neither is enforced by the current `Scheduler` (same pre-existing gap ADR-006 and ADR-019 both already named). This ADR does not newly break anything by wiring the job — it simply doesn't gain enforcement that has never existed for any job.
- **Product-state-aware notification timing.** `deadline_sweep`'s own status transition (`tracked → alerted`) is unconditional on state ("any," per Appendix E) — only the *notifier*'s delivery ladder is state-aware (already built, unaffected by this ADR, and already the correct layer for that concern per FR-074).
- **The `critical` escalation threshold** (03_ROADMAP §8 RESERVED row) — `deadline.sweep` already alerts at whatever lead thresholds are configured; ranking by urgency stays exactly as undefined as before.

---

## Consequences

- `kernel:scheduler`'s grant grows by one scope — reviewable in a single-line diff, matching the existing grant's own comment ("this line IS the answer to 'what can automation set off'").
- `deadline.sweep` runs automatically for the first time — lead-time alerts and missed-deadline detection (FR-031) stop depending on something manually invoking the operation. This is the actual product behavior this ADR exists to ship, not a side effect.
- Two jobs now share the scheduler; nothing about `_catch_up_job`/`tick()`/quarantine changes shape — proof that ADR-006's mechanism generalizes to a second job without new code is itself evidence worth having, not assumed.
- **What gets harder:** none — this is additive wiring over an already-decided mechanism, the same shape ADR-017 used for start-at-login (activating something already fully specified, not a new judgment call).

## Live verification (2026-08-11)

- **Automated, real-subprocess:** `suites/replay/test_boot_catchup.py::test_deadline_sweep_is_registered_and_boot_catches_up_a_missed_hour` — a real `serve()` subprocess, real `config/defaults/permissions.toml`/`kang.toml` copies (the actual shipped files this ADR edited, not stand-ins), `deadline_sweep` backdated 3 hours before boot. Asserts exactly one `job_run` row, `outcome='ok'` — proving the `deadlines.mark_alerted` grant this ADR added is genuinely there and lets the operation actually succeed, not merely that a row exists — while `morning_plan`'s own catch-up count independently stays at zero (two jobs, not one replacing the other).
- **Manual, throwaway `%KANG_HOME%`:** built fresh (never the real one), seeded with the real updated `permissions.toml`, a real `python -m kang.kernel.runtime.composition` process booted. `system.health` over real HTTP showed **both** `morning_plan` and `deadline_sweep` registered with the expected schedule/catch-up (`hourly`/`run_once_latest`), zero consecutive failures. A direct read of the real `job_run` table immediately after boot showed **zero rows** — the fresh-job/nothing-missed path, confirmed rather than assumed. Process stopped, throwaway home deleted.
- The real, persistent Core (`%KANG_HOME%` = `C:\Users\meime\kang-home`) was **not** restarted as part of this verification — its own `config/permissions.toml` still needs the same one-line grant applied before it will actually dispatch `deadline.sweep` successfully (it registers the job either way via the shipped `_wire_scheduler` code path once restarted onto this commit, but the operation would fail with `PermissionDenied` until the grant is copied in). That real-environment step is intentionally separate from ADR acceptance, same as ADR-008/019's own restart step.
