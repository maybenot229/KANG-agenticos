# ADR-022 — `held_action.expire`: the missing operation wrapping `expire_due()`, wired as a third automatic job

**Status:** accepted
**Date:** 2026-08-13
**Affected documents:** 12_API §7 (a new operation exposing an existing store contract), `05_AGENTS` Appendix E (the scheduling table — a third row alongside `morning_plan`/`deadline_sweep`), `src/kang/api/registry/__init__.py`, `src/kang/kernel/runtime/composition.py`, `config/defaults/permissions.toml`
**Cites:** ADR-020 (the pattern this ADR applies — a second automatic job wired the same way), ADR-006 (jobs dispatch through the normal operation pipeline; a job needs a registered operation to invoke), 12_API §7 ("24h expiry ⇒ `cancelled`" — the contract `expire_due()` already implements, unreachable until now)
**Related:** [[020-deadline-sweep-automatic-job.md]] (the last job wired this exact way — the difference this ADR names explicitly below)

---

## Context

`HeldActionStore.expire_due(now)` — "cancel every pending held action past its expiry as of `now`... the 24h sweep" — has existed since M3, fully implemented in both adapters (`SqliteHeldActionStore`, `FakeHeldActionStore`), and has **no caller anywhere in `src/`**. Confirmed by grep, not assumed: the only hits outside the two implementations and the domain port's own protocol definition are the method's own definitions — including a comment in `held_action_ops.py` that already self-names the gap ("`HeldActionStore.expire_due`, not wired to a job yet").

**This is not a pure application of ADR-020's pattern, and that matters for scope.** `deadline.sweep` already existed as a manually-invocable, registered operation before ADR-020 — that ADR's entire job was adding the `Job` row and the permission grant. `expire_due()` has no operation wrapping it at all. Wiring it as a job first requires deciding a new operation's shape (name, scope, schema, idempotency, event publication) — real judgment ADR-020 never had to exercise. That is the trigger for this ADR, per the same threshold ADR-020 and ADR-021 both already used.

---

## Decision

### 1. A new operation: `held_action.expire`

Mirrors `deadline.sweep`'s exact shape (`DeadlineSweepRequest`/`Response`'s own pattern): `kind="command"`, no request fields, response `{"count": int}` (the store's own return value — `expire_due()` returns a count, not a list of ids; this ADR does not expand that contract, only exposes it). `idempotent=True` — expiring a slot twice degrades to zero further work by construction, no special-casing needed. New scope `held_actions.expire` (mirrors `deadlines.mark_alerted`'s naming: domain-plural noun + the verb the operation actually performs). No `first_party_only` — same as `deadline.sweep`, this is routine automated cleanup, not an approval decision itself.

**No event publication.** Checked, not assumed: no `held_action.*` event type is registered anywhere (`event_registry.py`). `deadline.sweep` publishes `deadline.updated` because that event has real consumers (the notifier). Inventing a `held_action.expired`/`.updated` event with no named consumer would repeat the exact "enum allows it" anti-pattern ADR-021 already declined for `job.enable`/`.disable`'s own event question. Revisit if a real UI/notification need for expiry visibility appears.

### 2. The job

A third `Job` row, registered in `_wire_scheduler` alongside `morning_plan`/`deadline_sweep`: `id="held_action_expire"`, `catch_up="run_once_latest"` (same reasoning as `deadline_sweep`'s: checking "now" once after downtime catches everything currently past-expiry — replaying missed slots would recompute the identical result). `JOB_OPERATIONS["held_action_expire"] = "held_action.expire"`.

### 3. Cadence — proposed and justified, not picked

**`schedule="daily"`** (the existing interval literal, anchor-relative, no cron/wall-clock needed — same class of decision `deadline_sweep`'s `"hourly"` already was). Reasoning: the window this sweep protects is 24 hours (12_API §7's own expiry constant). `deadline_sweep`'s hourly cadence was proportionate to a hazard that compounds hourly (a deadline crossing its lead threshold has real time-sensitivity for Kang's plan). A stale pending approval has no equivalent urgency — the cost of it sitting an extra few hours past its technical expiry is a cosmetic staleness in the approval queue, not a missed real-world event (the *action* itself was never approved; nothing was left undone by the sweep running late). Checking daily is proportionate to the 24h window it's cleaning up after (roughly once per window, same ratio `deadline_sweep`'s hourly cadence holds against a much shorter-lived hazard), and avoids running a job every hour for a condition that, in practice, changes at most once every 24h per action. If real use ever shows a stale-queue-visibility complaint, this is a one-line cadence change, not a design question — the operation and job wiring don't need to change.

### 4. Grant

`permissions.toml`: `"kernel:scheduler" = ["tasks.write", "deadlines.mark_alerted", "held_actions.expire"]` — same shape ADR-020 added `deadlines.mark_alerted` in.

---

## Consequences

- **New operation, new scope, new job** — all three real additions, all mirroring existing precedent exactly (`deadline.sweep`'s schema shape, ADR-020's job/grant wiring), no new mechanism invented.
- **`expire_due()` finally has a live caller** — pending held actions past their 24h window now genuinely transition to `cancelled` in the real running Core, not only in tests.
- **What gets harder:** nothing structural — this is the third instance of a now well-established pattern (job → operation → store call), proof the pattern keeps generalizing.
- **Explicitly not decided here:** whether `held_action.expire` should ever be manually invocable from a UI affordance ("sweep now," mirroring a hypothetical `deadline.sweep` manual trigger) — no such affordance exists for either operation today; not a new gap this ADR introduces.

---

## Live verification (2026-08-14)

Against a real, throwaway `%KANG_HOME%` (never the real one), a real `python -m kang.kernel.runtime.composition` process:

- Backdated `held_action_expire` by 2 days and seeded a real, genuinely-expired `pending` held action directly in `kang.db` before boot.
- `system.health` after boot showed all three jobs registered (`morning_plan`, `deadline_sweep`, `held_action_expire`), healthy, zero consecutive failures.
- The seeded held action's row genuinely transitioned `pending → cancelled` — confirmed by direct `kang.db` read, not asserted — and `job_run` shows exactly one run for `held_action_expire`, `outcome='ok'` (boot catch-up, `run_once_latest`).
- A manual `held_action.expire` call afterward returned `{"count": 0}` — idempotent, nothing left to sweep, proving the operation channel path (not just boot catch-up) works too.
- Process stopped, throwaway `%KANG_HOME%` deleted. The real, persistent Core was not touched.

This is also proven automatically, not just this once: `suites/replay/test_held_action_expire_is_registered_and_boot_catches_up_a_missed_day` runs the identical shape (real subprocess, real backdated job, real seeded expired held action, direct `kang.db` read of the resulting status) on every test run.
