# ADR-006 — Wall-clock (cron) schedules, and how a job invokes an operation

**Status:** proposed
**Date:** 2026-07-27
**Affected documents:** 04_ARCHITECTURE D014 (the deferral this ADR discharges), 07_DATABASE §5.5 (`job.schedule` values), 12_API §14 (scheduled work reaches the system through registry-listed commands), 05_AGENTS Appendix E (the schedules themselves), 17 §2 (a new `adapters/scheduler/` technology folder)
**Cites:** D014 ("schedules are cron-like"; "APScheduler … may be used *inside* the adapter, behind our `Scheduler` port"), 17 §4.2 (kernel MUST NOT import api), SEC-003/SEC-004/SEC-005, API-003/API-004, E10 (boring tech; justify every dependency)
**Related:** [[002-approval-channel.md]] (why a job is structurally unable to approve a held action)

---

## Context

M5 owes an automatically-triggered morning plan. Three things block it, and
they are tightly coupled — a schedule that cannot name a time and a job that
cannot invoke anything are each half a feature, so they are decided together.

**1. The schedule grammar cannot express the requirement.** `parse_schedule`
supports `every:{seconds}`, `daily`, `hourly`, `minutely`, `event:{type}`.
These are *interval grids anchored at the job's creation time*, not
wall-clock times: `daily` means "86400s after the anchor", so a job created
at 14:23 fires at 14:23 forever. There is no way to say 05:45, and — the
harder constraint — no way to say **05:45 Monday–Saturday but 06:45 Sunday**,
which is Kang's actual routine (`config/defaults/kang.toml`, grounded in the
2026-07-19 intake; Saturday is a school day). The module's own docstring
already names this gap and defers it to "the Scheduler adapter (D014)".

**2. Nothing bridges a job to an operation.** `Scheduler` takes an injected
`JobRunner = Callable[[Job, datetime], None]` and calls it. No implementation
of that callable exists. Note the shape: the seam is *already designed* —
what is missing is an implementation, not an abstraction.

**3. No job is registered and the scheduler is not in the Core.**
`register_job` is called nowhere in `src/`; `Scheduler`, `JobStore`, and
`KillSwitch` appear nowhere in `composition.py`. `deadline_sweep` — which
looked like an existing precedent to copy — is an **API operation**
(`deadline.sweep`), not a scheduled job. `morning_plan` would be the first
job row in the system.

Point 3 is confirmed scope for this increment and needs no ruling. Points 1
and 2 are the decisions below.

---

## Part A — Wall-clock schedules

### A. Options

**A1 — Extend the existing interval grammar with a time-of-day form**
(e.g. `daily@05:45`).

- *For:* small change; no new folder.
- *Against:* a bespoke grammar for a solved problem, and it still cannot
  express per-weekday times without growing further (`daily@05:45;sun@06:45`
  — at which point it is cron with worse syntax and no shared understanding).
  D014 says "cron-like", and inventing a private dialect is exactly the
  vocabulary-invention 11 §3 forbids. **Rejected.**

**A2 — Standard 5-field cron, one expression per job row** (`45 5 * * 1-6`).

- *For:* real, universally-understood syntax; exactly what D014 named.
- *Against:* **cron cannot express two different times on different days in
  a single expression.** A crontab solves that with two lines; one `job` row
  holds one `schedule` string. Modelling it as two job rows
  (`morning_plan_weekday`, `morning_plan_sunday`) splits one ritual into two
  identities with *two independent catch-up baselines* — after downtime
  spanning Saturday into Sunday, each would independently run its own latest
  missed slot and generate the plan twice. Catch-up is per-job by design
  (D014), so this is a real defect, not a cosmetic one. **Rejected.**

**A3 — A list of standard cron expressions per job (recommended)**
(`cron:45 5 * * 1-6 | 45 6 * * 0`).

- *For:* still standard cron — a crontab *is* a list of expressions, so this
  is supporting the same thing crontab does rather than inventing a dialect.
  Keeps **one job identity and one catch-up baseline**, which matters
  precisely because the morning brief is one ritual and `run_once_latest`
  must mean "one plan". Occurrences are the union of the expressions,
  deterministically sorted — the property `occurrences_in` already promises.
- *Against:* one separator character beyond bare cron. Accepted as the
  minimum honest extension.

### A. Decision

Adopt **A3**. A new `cron:` schedule form holding one or more standard
5-field cron expressions separated by `|`, parsed in a new
**`adapters/scheduler/`** technology folder behind the existing `Schedule`
contract — the adapter D014 explicitly anticipated.

**The existing interface already fits.** `Schedule.occurrences_in(anchor,
after, until)` works unchanged: a cron schedule ignores `anchor`, because
cron is absolute wall-clock rather than anchor-relative. Adding cron is a new
implementation behind the same contract, **not** an interface change — so
`Scheduler._catch_up_job` and every catch-up policy keep working untouched,
and C3's catch-up convergence proof still holds.

**No new dependency.** D014 permits APScheduler inside the adapter, but a
5-field matcher over an occurrence range is small and exact, and E10 asks
what a decade of maintaining a dependency costs. Implement it directly;
APScheduler remains available behind the same port if real needs outgrow it.

### A. Timezone — the sub-decision that cannot be skipped

The `Clock` port **MUST return aware UTC** (its docstring is explicit, and
`SystemClock` returns `datetime.now(timezone.utc)`). Cron times are local
wall-clock. "05:45" is therefore meaningless without a timezone, and getting
this wrong silently shifts every future slot.

**Decision:** the timezone is **explicit configuration**, added to
`kang.toml` (Kang's is `Asia/Kuching`, UTC+8, per the intake), read by the
existing planner-config loader, and passed to the schedule adapter. It is
**not** taken from the host's local timezone: system-local silently changes
when the machine changes, and a laptop opened in another country must not
move Kang's morning brief. `zoneinfo` is stdlib, so this adds nothing.

DST is not a live concern for `Asia/Kuching` (no DST), but the adapter MUST
resolve local→UTC through `zoneinfo` rather than a fixed offset, so a future
timezone that does observe DST does not silently break. Ambiguous and
skipped local times are a real DST edge case; this ADR does **not** rule on
their handling — flagged for whichever ADR first ships a DST-observing
timezone, since inventing a rule now would be guessing at a case that cannot
arise for this user.

---

## Part B — How a job invokes an operation

### B. Options

**B1 — A narrow internal invocation path** (the runner calls domain services
directly, bypassing the API).

- *For:* no session ceremony.
- *Against:* creates a **second execution path with its own authorization
  story** — precisely what SEC-004 ("capabilities are the only authority
  model") and API-003 ("the API layer adds *no* second authorization
  vocabulary") exist to prevent. It would also skip the invocation ledger,
  so `explain.invocation` could not reconstruct why a job acted — breaking
  12 §12's ≥180-day guarantee for exactly the actions Kang did not watch
  happen, which is the case explainability matters *most*. **Rejected.**

**B2 — Through the normal Dispatcher, the same path a UI command takes
(recommended).**

- *For:* one path, uniformly permission-checked, idempotency-keyed,
  invocation-recorded, and audited (12 §5's pipeline). `explain.invocation`
  works for scheduled work for free, and the invocation ledger's `trigger`
  vocabulary **already anticipates this**: `'kang' | 'cli' | 'job:{id}' |
  'event:{type}'`. 12 §14 states the intent directly — scheduled work is
  "controllable *only* through the registry-listed commands".
- *Against:* the Dispatcher requires a session, and a job has none. Resolved
  below, and the resolution turns out to be a feature.

### B. Decision

Adopt **B2**, with four rulings:

**1. The seam is the existing `JobRunner`, implemented at the composition
root.** `kernel → api` is forbidden (17 §4.2's matrix), so `Scheduler` MUST
NOT import the Dispatcher — and it does not need to: the runner is injected.
The composition root, the one module exempt from the matrix, builds a closure
that dispatches. No import rule bends, and no new abstraction is introduced.

**2. The scheduler dispatches under a minted session bound to principal
`kernel:scheduler`, with `first_party = False`.**
`kernel:scheduler` is **already established vocabulary** — the Scheduler
audits under exactly that principal today (`automation.paused`,
`job.quarantined`), so this names nothing new.

`first_party = False` is the important half, and it is a *feature, not a
limitation*: per [[002-approval-channel.md]], first-party means "arrived
out-of-band through Kang's own UI". A job is not Kang's hand. Therefore a
scheduled job is **structurally incapable of approving a held action** —
which is SEC-003 ("consequences require live human confirmation") enforced by
construction rather than by remembering. A future contributor who "fixes"
this by minting first-party sessions for jobs would silently hand automation
the power to approve its own consequences.

**3. Idempotency keys are derived deterministically from `(job.id, slot)`.**
A replayed slot then returns the cached outcome instead of re-executing
(API-004). This is defence in depth, not the primary guard: the durable
guard remains the `job_run` baseline, because API-004's key retention is
7 days and a slot replayed after longer would re-execute. Stated so the
7-day limit is a known bound rather than a surprise.

**4. The job → operation mapping is an explicit table in the composition
root.** The `job` table has no `operation` column (07 §5.5) and job names are
ritual names (`morning_plan`), not operation names (`plan.generate`) — 05
Appendix E is explicit about that. The mapping therefore has to live
somewhere; the composition root is the one place permitted to know both
layers, and putting it in `api/registry` would make the API layer know about
jobs, which it otherwise does not. It MUST stay a plain, greppable literal:
SEC-005 forbids hidden execution, and P5 asks that "what will KANG do next
and why" be answerable. Serving it to a UI is M6's concern, not this ADR's.

---

## Consequences

- **New technology folder `adapters/scheduler/`** (17 §2 lists adapter
  folders as one-per-technology; this is the cron parser's home). No new
  top-level directory, so no 17 §17.1 trigger.
- **`kang.toml` gains a timezone key**; the planner-config loader gains a
  field. Fail-fast if absent, like every other trigger value — an invented
  default timezone is an invented schedule.
- **`permissions.toml` gains `kernel:scheduler`** holding the scopes of the
  operations it may invoke (`tasks.write` for `plan.generate`). Default-deny
  means the answer to "what can automation trigger?" is one reviewable file —
  a property worth having deliberately, not a chore.
- **The Core gains the scheduler**: `JobStore`, `KillSwitch`, `Scheduler`,
  and a `catch_up()` call at startup. Jobs are registered idempotently by
  name (`register_job` is already insert-or-replace).
- **What gets harder:** two schedule dialects now coexist (`every:`/`daily`
  intervals and `cron:` wall-clock). That is real surface. Accepted because
  the interval forms are exact and deterministic for *relative* cadences
  (health ticks, sweeps) where a wall-clock time would be meaningless, while
  rituals genuinely need wall-clock. Neither subsumes the other. A future
  ADR may retire the interval forms if they prove unused, but deleting them
  now would break `deadline_sweep`'s intended `hourly` cadence.
- **Explicitly NOT decided here** (flagged, not guessed):
  - **`job.timeout_s` is not enforced.** The column exists and `Scheduler`
    calls the runner synchronously, so a hung job hangs catch-up. Real, and
    out of scope: it needs the supervised-task machinery D014 names, which
    is a separate concern from scheduling. Not introduced by this ADR — the
    gap is pre-existing.
  - **DST ambiguous/skipped local times** (Part A above).
  - **The "deadline in danger today" `critical` threshold**, already carried
    in 03_ROADMAP §8's RESERVED registry — unchanged by this ADR.

## Amendment — 2026-07-27 — missing config fails closed, not dead

**Status:** accepted (found in implementation).

The Consequences above said a missing timezone should "fail fast, like every
other trigger value". Implementing it showed that reading is too strong: it
made `build_core` raise, so a missing *optional* config file took the whole
Core down — the API, manual task capture, everything — not just automation.

**Amended:** missing or invalid `kang.toml` disables the scheduler and leaves
the rest of the Core running, recording `automation.unconfigured` to the
audit log. This is the shape 07 F8 already uses for `permissions.toml`
(fail closed to Kang-only rather than refuse to boot).

The principle the original wording was protecting is unchanged and still
enforced: **never invent a timezone or a trigger time.** Declining to
schedule is not the same as inventing a schedule. Bricking manual use of the
system over an absent file is the worse failure, and a silent one at that —
whereas "automation is off, here is why, in the audit log" is a visible,
specific degradation (SEC-009).
