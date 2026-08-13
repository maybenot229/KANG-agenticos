# Session handoff — 2026-08-13

Everything below was verified against the actual repo state at handoff time (git log, a fresh full test run, a fresh lint run, fresh UI typecheck/build/test, and the real running Core's own `registry.get`/`system.health`/`kang.db` job and held_action history) — not recalled from memory or from an earlier version of this same file. This is an in-place update of the day's own handoff (first written after the `job.timeout_s` work, now covering ADR-021 too) — it supersedes `session-handoff-2026-08-11.md`, which the day's first session picked up from at commit `649d051`.

---

## 1. State (verified just now)

```
git status --porcelain                    → (empty — clean working tree)
git rev-list --count origin/main..HEAD    → 0 (everything pushed)
python -m pytest tests/unit tests/suites tests/integration -q → 808 passed
ruff format --check src tests tools cli   → 296 files already formatted
ruff check src tests tools cli            → All checks passed!
lint-imports --config tools/importlinter.toml → Contracts: 8 kept, 0 broken
python tools/lint_sizes.py src            → 0 hard violation(s), 55 soft warning(s)
python tools/lint_banned_patterns.py src  → 0 violation(s)
python tools/lint_tree_hygiene.py .       → 0 violation(s)
python tools/build_root_docs.py --check   → CLAUDE.md is current.
cd ui && npm run typecheck && npm run build && npm run test → all clean, 62/62 UI tests
```

`main` is at `45b6f3d`, fully pushed — **nothing local, nothing unpushed.**

**The real, persistent Core is running right now — PID 20896, started 2026-08-13 8:05:03 PM**, confirmed via its own `registry.get` (**38 operations** — 36 + `job.disable`/`job.enable`, ADR-021) and `system.health` (`morning_plan` + `deadline_sweep` both registered, enabled, zero consecutive failures). Lock genuinely held (`msvcrt.locking()` from outside the process fails with `PermissionError`). This is a later restart than the one this session performed after committing ADR-021 (PID `12408`) — the Core was restarted again after that, outside this session's own actions, but the op count and job list confirm it's still running current code, not stale.

**Automation continues running cleanly in Kang's real life.** `deadline_sweep` has now fired repeatedly through today (most recent real runs: 07:26, 11:26, 12:26, 13:26, 14:26 UTC, all `outcome='ok'`), `morning_plan` fired again this morning. Zero `job.overrun`, zero `job.quarantined`. The real `held_action` table is empty — correct and expected: every live-verification this session ran against throwaway `%KANG_HOME%`s, never the real one.

### Commits landed today (chronological)

```
35a276c feat(kernel): job.timeout_s soft overrun signal (D014)
e352d19 docs: session handoff — 2026-08-13 (superseded by this update)
c99c6a3 docs: record job-level retry-with-backoff as not ripe (03_ROADMAP §8)
45b6f3d feat(kernel): job.enable/job.disable, the first real consequential operation (ADR-021) - accept
```

Two real design conversations, two real outcomes — one "ship the cheap honest partial answer," one "ship the whole thing, it turned out ripe."

---

## 2. What's actually built now

### `job.timeout_s`'s soft overrun signal (D014, no ADR)

A real design conversation (read D014, AG-007, DB-001, the actual job handlers) ruled hard enforcement not ripe: Python cannot force-kill a thread, Windows has no `SIGALRM`, and both wired jobs (`plan.generate`, `deadline.sweep`) are confirmed-by-reading zero-model-call pure SQL — nothing AG-007's cooperative-cancellation model (a Phase 3, unbuilt agent-invocation concept) was designed for. `Scheduler._record_overrun_if_any` times the already-blocking runner call via the injected `Clock` and audits `job.overrun` — post-hoc only, never enforcement, never touching the run's outcome or quarantine count. `deadline_sweep` carries an explicit `timeout_s=120` (05_AGENTS Appendix A names it directly); `morning_plan` stays at the schema default (300s) — the planner *agent's* "10m" is a budget across three different job triggers, not morning_plan's own number, deliberately not reused. **Live-verified** against a real, continuously-running (never restarted) throwaway Core via the *live tick* itself, not a fresh boot: `timeout_s` patched to `0` mid-session, the next tick produced a real `job.overrun` entry while the run still completed `outcome='ok'`.

### Retry-with-backoff — ruled not ripe (03_ROADMAP §8 RESERVED, no code)

D014's *other* named "supervised task" property, alongside timeout. Real design conversation, real conclusion: no schema exists for it at all (unlike `timeout_s`), the catch-up baseline advances on *any* outcome including failure (so retry can't happen across ticks without weakening the already-proven convergence guarantee — a real, previously-unnamed finding), and neither wired job has a transient-failure mode worth retrying selectively on. Recorded as a RESERVED row with a real trigger (a job with a genuine transient failure mode, plus failure classification in the job→operation path) rather than left only in conversation.

### ADR-021 — `job.enable`/`job.disable`: the first real consequential operation

`held_action`'s lifecycle store existed since M3, fully tested in isolation, **zero live callers** — confirmed by grep, nothing in `src/` ever raised `confirmation_required` or called `held_actions.create()` before today. This is the follow-through: `job.enable`/`job.disable` (already named in `12_API.md:182`, not a new decision) are the first operations to exercise 05_AGENTS Appendix D's consequential gate for real, end to end.

- **The gate**: `job.disable`/`job.enable`'s own handlers never perform the effect on any call — always create a `HeldAction` and raise `confirmation_required`, via a new shared helper (`require_confirmation`, `api/operations/consequential.py`) every future consequential command reuses.
- **Schema**: `held_action` gains `params` (JSON, migration `0015`, mirrors `notification.payload`'s existing pattern) — the delta ADR-001's Consequences called "owed," finally applied.
- **Driving the effect**: `held_action.approve`'s handler was rewritten. For `commit_mode="transactional"` (resolved from the *target* operation's own registry entry), it drives the approve-flip, the target's effect (`TRANSACTIONAL_EFFECTS`, composition.py — same plain-literal shape `JOB_OPERATIONS` already established), and `mark_executed` inside **one real `BEGIN`/`COMMIT`** — the first actual implementation of ADR-001 Amendment's "a crash before commit is indistinguishable from still-pending" promise. New `_in_txn` store-method variants (`HeldActionStore.approve_in_txn`/`mark_executed_in_txn`, `JobStore.set_enabled_in_txn`) assume the caller already owns the transaction. `redrive` mode (`calendar.write`) is untouched — falls back to the pre-ADR-021 flip-only behavior.
- **Found in implementation, fixed the established way**: `require_confirmation`'s naive signature (9 params) and `job_ops.py`'s internal gate-builder (7 params) both crossed the size lint's hard parameter limit — fixed with `ConfirmationDeps`/`ConfirmationRequest`/`_GateSpec` dataclasses, not a relaxed limit. `composition.py` crossed the file-level 800-line hard limit the moment this wiring landed — `_build_consequential_handlers` extracted, mirroring `_build_project_cluster_handlers`'s own precedent from the ADR-018 session.
- **Live-verified twice**: real SQLite integration tests (including a forced-failure test proving a failing effect rolls back *both* the held-action flip and the target write — not just individually asserted), plus a real throwaway Core driven entirely over HTTP: `job.disable` → `confirmation_required` (job still enabled) → `held_action.approve` → `executed` → `system.health` confirms the job genuinely disabled; round-tripped both directions; `kang.db` and the audit log directly inspected.

---

## 3. Architectural notes worth knowing

- **Windows' lack of `SIGALRM` and Python's inability to force-kill a thread are now load-bearing, documented facts** — `scheduler.py`'s own module docstring states both as the reason `job.timeout_s` enforcement isn't ripe.
- **The catch-up baseline advancing on *any* outcome (including failure) is what makes retry-with-backoff genuinely hard, not just unbuilt** — `JobStore.last_slot`'s docstring already said this, but its implication for retry (can't happen across ticks without weakening the C3 convergence guarantee) had never been traced through before this session.
- **`commit_mode` on a registry entry describes *that operation's own* effect, not the operation named inside a held action it might process** — `held_action.approve`'s own entry has always declared `commit_mode="transactional"` for its own status-flip write; ADR-021's new code looks up commit_mode from the *target* operation's entry instead, a distinct and easy-to-conflate concept the code now comments explicitly.
- **The AG-007 (agent invocation) vs. `job.timeout_s` (kernel scheduler) distinction, and the "gate vs. effect-driver are two different code paths sharing an operation name" distinction (ADR-021)** are both now explicit in code comments, not just implied — both are the kind of thing a future contributor could plausibly "simplify" into one path, and both comments say directly why that would be wrong.
- **Composition.py is now sitting right at the 800-line hard limit again** (trimmed back to exactly 800 after ADR-021's extraction) — the next addition to this file will likely need a real split, not another same-file extraction. Worth planning for, not just reacting to next time.

---

## 4. Known, named, real gaps — not forgotten, deliberately not built

1. ~~**`held_action.approve` → `executed`**~~ — **closed today (ADR-021)**, for `commit_mode="transactional"`. `redrive` mode (`calendar.write`) remains open — needs a proven adapter idempotency contract first (ADR-001 Amendment's own gate).
2. ~~**Retry-with-backoff**~~ — **ruled not ripe today**, recorded in 03_ROADMAP §8 with a real trigger.
3. **`project.pause`/`.resume`/`.archive`/`.abandon`** — unchanged, not re-examined.
4. **No real D016 packaged installer** — unchanged, not re-examined.
5. **Learn/Know/Chat** — unchanged, not re-examined.
6. **Event-triggered job admission** (`schedule = 'event:{type}'`) — still parsed, still unwired anywhere.
7. **No event publication** (`job.updated`) for `job.enable`/`.disable` — ADR-021's own named, deliberate omission (no current consumer; building it speculatively would repeat the `project.pause` "enum allows it" anti-pattern).
8. **No de-duplication of repeated `job.disable` calls carrying the same idempotency key** — ADR-021's own named, minor rough edge. Confirmed by reading `dispatch.py::_execute`: `_store_idempotent` only runs on the success path, so a retried gate call creates a second `held_action` row rather than replaying the first. Not a safety issue (nothing executes twice; Kang can cancel the duplicate).

---

## 5. Working discipline today (keep doing this)

- **Two real design conversations, two different honest outcomes** — timeout got a cheap partial answer; retry got a clean "not ripe" with a real, previously-undiscovered reason (the catch-up baseline); `held_action.approve → executed` turned out to be genuinely ripe once actually scoped, and was built in full rather than partially, because the scope (transactional mode only, `job.enable`/`.disable` only) was real and bounded, not because "just build the whole thing" was the default instinct.
- **A "not ripe" verdict got recorded where future sessions will actually see it** (03_ROADMAP §8's RESERVED registry), not left to live only in a handoff paragraph that will eventually scroll out of the "last few days" window.
- **A real mechanical gap (no cross-store transaction primitive existed anywhere) was found by checking, not assumed** — grepped every store's write methods before designing ADR-021's transaction-sharing mechanism, rather than assuming one already existed or inventing a general-purpose primitive for a two-caller need.
- **Size-lint violations found in implementation were fixed the way this codebase already fixes them** (dataclasses for parameter counts, function extraction for file length) — not by relaxing a limit, and named as "found in implementation" in the ADR rather than silently absorbed.
- **Live-verified everything against real running Cores**, never just unit tests — including a forced-failure test proving a transaction rollback for real, not asserted from the shape of the code.
- **Commit per coherent slice, real messages via `git commit -F <file>`, never inline `-m`** — held all day.
- **Never pushed without explicit instruction** — held; pushed only when asked, after a fresh full test run each time.
- **Restarted the real Core specifically because new backend code landed**, confirmed live and the lock genuinely held before calling each piece of work done.
- **Cleaned up every throwaway `%KANG_HOME%` and process** — PowerShell `Get-Process`/`Stop-Process` throughout.

---

## 6. Next step

Pick based on priority — none of these is committed to:

1. **`held_action.approve` → `executed` for `redrive` mode** — `calendar.write` (or whichever world-touching operation comes first) needs a proven adapter idempotency contract before it can register `commit_mode="redrive"` (ADR-001 Amendment's own gate). Real, separate design work — the adapter choice and its idempotency story haven't been decided at all yet.
2. **Watch the next few real automation cycles, now with `job.enable`/`.disable` live too** — worth a spot-check in a week or two that nothing's accumulating unexpectedly, and that the two new operations, once Kang actually uses them for real (not just this session's live-verification), behave as designed.
3. **CSS/visual polish on the transition buttons** — still functional, minimally styled. Not urgent.
4. **A real split of `composition.py`** — it's sitting exactly at the 800-line hard limit; the next addition to it will need a genuine module split, not another same-file function extraction. Worth doing proactively rather than under pressure next time something needs to land there.
5. Something else entirely — Know/Chat both still blocked on Phase 2/Phase 3 architecture that doesn't exist yet.

Before doing real work: run `git status`, `git log --oneline -15`, the full test suite, and check whether the real Core needs a restart (compare its live `registry.get` operation count — should be 38 or higher — `system.health`'s job list, and its real `job_run`/`held_action` history, against `%KANG_HOME%/core.lock` actually being held by the process you think is running it). The real Core was restarted at least twice today by forces outside any single session's own actions — don't assume the PID you last saw is still the one running, and don't assume "it's running" means "it has today's code." Check directly, every time.
