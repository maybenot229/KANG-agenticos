# Session handoff — 2026-08-13

Everything below was verified against the actual repo state at handoff time (git log, a fresh full test run, a fresh lint run, fresh UI typecheck/build/test, and the real running Core's own `registry.get`/`system.health`/`kang.db` job history) — not recalled from memory or from the prior handoff. This supersedes `session-handoff-2026-08-11.md`, which this session picked up from at commit `649d051`.

---

## 1. State (verified just now)

```
git status --porcelain                    → (empty — clean working tree)
git rev-list --count origin/main..HEAD    → 0 (everything pushed)
python -m pytest tests/unit tests/suites tests/integration -q → 779 passed
ruff format --check src tests tools cli   → 290 files already formatted
ruff check src tests tools cli            → All checks passed!
lint-imports --config tools/importlinter.toml → Contracts: 8 kept, 0 broken
python tools/lint_sizes.py src            → 0 hard violation(s), 54 soft warning(s)
python tools/lint_banned_patterns.py src  → 0 violation(s)
python tools/lint_tree_hygiene.py .       → 0 violation(s)
python tools/build_root_docs.py --check   → CLAUDE.md is current.
cd ui && npm run typecheck && npm run build && npm run test → all clean, 62/62 UI tests
```

`main` is at `35a276c`, fully pushed — **nothing local, nothing unpushed.**

**The real, persistent Core is running right now — PID 14080, started 2026-08-13 05:36:51 AM**, confirmed via its own `registry.get` (36 operations, unchanged) and `system.health` (`morning_plan` + `deadline_sweep` both registered, zero consecutive failures). Lock genuinely held (`msvcrt.locking()` from outside the process fails with `PermissionError`, same check every prior handoff has used).

**Automation has now genuinely run in Kang's real life, multiple times, with zero failures.** This is new since the last handoff, worth stating plainly: `morning_plan` has fired for real twice (2026-08-11 21:45 UTC and 2026-08-12 21:45 UTC — both 05:45 local, both `outcome='ok'`), `deadline_sweep` has fired seven times hourly (all `outcome='ok'`, correctly catching up as a single run rather than replaying every missed hour after gaps — e.g. one gap from 07:26 to 20:26 UTC on 2026-08-12, almost certainly the machine asleep, caught up once on wake per `run_once_latest`). Zero `job.overrun`, zero `job.quarantined` in the real audit log.

### Commits landed this session (chronological)

```
35a276c feat(kernel): job.timeout_s soft overrun signal (D014)
```

One commit. A real design conversation (read D014, AG-007, DB-001, and the actual handlers for both wired jobs before concluding anything) ruled hard enforcement not ripe — Python cannot force-kill a thread, Windows has no `SIGALRM`, and both `plan.generate`/`deadline.sweep` are confirmed-by-reading zero-model-call pure SQL, nothing that could hang the way AG-007's cooperative-cancellation model (a Phase 3 agent-invocation concept that doesn't apply here) was designed for. What shipped instead was the cheap, honest option: a post-hoc, purely observational `job.overrun` audit signal. No ADR — additive observability instantiating D014's already-decided "health status on the dashboard," touching no authority path, dependency, or directory.

---

## 2. What's actually built now

Live-verified against a real, continuously-running (never restarted mid-test) throwaway Core, same discipline as every session before this one.

- **`job.timeout_s`'s soft overrun signal.** `Scheduler._record_overrun_if_any` times the already-blocking runner call around `self._runner(job, slot)` via the injected `Clock` (never wall time — 11 §25), and if the elapsed time exceeds `job.timeout_s`, audits `job.overrun` — `{job, elapsed_s, timeout_s}` under `kernel:scheduler`. Purely post-hoc: it never affects the run's actual outcome, never touches quarantine counting, and cannot stop a hung call (the whole point of "soft"). `deadline_sweep`'s job row now carries an explicit `timeout_s=120` (05_AGENTS Appendix A names it directly for that job); `morning_plan` stays at the schema default (300s) — the planner *agent's* "10m" in Appendix A is a budget across three different job triggers (morning_plan/evening_review/weekly_close), not morning_plan's own number, and reusing it would have been inventing a figure nothing actually names.
- **Live-verified for real, not just with a fake clock.** A throwaway Core was booted, `deadline_sweep`'s `timeout_s` was patched to `0` directly in the running Core's own `kang.db` mid-session (after boot registration, so the patch actually stuck rather than being overwritten by the next `register_job` insert-or-replace), the job was backdated so it had a slot due. The **live tick** (ADR-019, no restart) picked it up on its own and produced a real `job.overrun` audit entry (`elapsed_s=0.052`) — while the run itself still completed `outcome='ok'`, proving the signal is genuinely observational end to end, not a side door into enforcement.

---

## 3. Architectural notes worth knowing

- **Windows' lack of `SIGALRM` and Python's inability to force-kill a thread are now a load-bearing, documented fact**, not folklore — `scheduler.py`'s own module docstring states both explicitly as the reason real enforcement isn't ripe, alongside DB-001's thread confinement (which ADR-019 already worked around for the *tick*, not for *job bodies* — a hung job body still blocks the single request-handling thread, tick loop included, exactly as before).
- **`Job.timeout_s` was already a real DB column** (migration `0003_scheduler.sql`, `Job` dataclass, `SqliteJobStore`/`FakeJobStore` round-trip) with a schema default of 300s — nothing new had to be added to the store layer or schema. The entire feature was: read it, compare it, audit it. Worth knowing for anyone assuming "supervised tasks" (D014's phrase) implied more infrastructure was missing than actually was.
- **The distinction between an *agent's* AG-007 timeout and a *job's* `timeout_s`** is now explicit in the code, not just implied by the docs: AG-007's "cooperative cancellation → 10s grace → hard kill" belongs to the (unbuilt, M7) Agent Runtime's invocation envelope; `job.timeout_s` is the kernel scheduler's own, older, narrower concept, and jobs today dispatch straight to operations (ADR-006), never through an agent. Conflating the two would have been the kind of "second name for an existing concept, in reverse" mistake the constitution warns about — confirmed distinct before writing any code.

---

## 4. Known, named, real gaps — not forgotten, deliberately not built

Unchanged from the 2026-08-11 handoff except item 7, now more precisely scoped:

1. **`held_action.approve` → `executed`** — still blocked; unchanged, not touched this session.
2. **`project.pause`/`.resume`/`.archive`/`.abandon`** — unchanged, not re-examined.
3. **No real D016 packaged installer** — unchanged, not re-examined.
4. **Learn/Know/Chat** — unchanged, not re-examined.
5. **Event-triggered job admission** (`schedule = 'event:{type}'`) — still parsed, still unwired anywhere. Unaffected by this session.
6. ~~**`job.timeout_s`/retry-with-backoff enforcement**~~ — **ruled not ripe this session, deliberately, with a real design conversation, not silently skipped.** A *soft* overrun signal shipped instead (§2 above). Real enforcement needs a killable-subprocess design (the job body isolated from the parent's `kang.db` connection, with its own IPC back through the operation channel) — genuinely separate, real infrastructure, revisit if a job that can actually hang (network/model calls) ever gets scheduled. Neither wired job can today.
7. **Retry-with-backoff** (D014's other named "supervised task" property, alongside timeout) — still entirely unbuilt; `_maybe_quarantine` is the only failure-accumulation mechanism that exists (3 consecutive failures ⇒ quarantine, no retry attempt in between). Not addressed this session; worth naming as its own future gap distinct from timeout enforcement, since D014 lists them as separate properties.

---

## 5. Working discipline this session actually followed (keep doing this)

- **A real design conversation before building, and it was allowed to be short because the answer was genuinely clear** — unlike ADR-019 (a real fork between mechanisms) or ADR-020 (fully pre-specified, just needed a grant), this one's honest conclusion was "the cheap partial answer, not the full one" — read D014/AG-007/DB-001 and the actual job handlers before ruling, not reasoning from the prior session's own framing of the gap.
- **Confirmed a fact before relying on it** — "both wired jobs are zero-model-call pure SQL" was verified by reading `plan.generate`'s and `deadline.sweep`'s own handler code and docstrings directly, not assumed from Appendix E's summary table.
- **Live-verified with a real, continuously-running Core**, and specifically exercised the *live tick* path (ADR-019) rather than a fresh boot, to prove the signal fires from ongoing operation, not only at startup — the harder, more honest version of the test.
- **A live-verification wrinkle got caught and understood, not worked around** — patching `timeout_s` in the DB *before* boot got silently overwritten by `register_job`'s insert-or-replace on that same boot; recognized as expected behavior (not a bug) and the test was restructured to patch *after* boot, which is also the more realistic scenario for verifying the live tick specifically.
- **Commit per coherent slice, real message via `git commit -F <file>`, never inline `-m`** — held.
- **Never pushed without explicit instruction** — held; pushed only when asked, after a fresh full test run.
- **Restarted the real Core specifically because new backend code and config landed**, confirmed live (`registry.get`, `system.health`, direct `kang.db` inspection for `timeout_s`) and the lock genuinely held before calling it done.
- **Cleaned up every throwaway `%KANG_HOME%` and process** — PowerShell `Get-Process`/`Stop-Process` throughout.

---

## 6. Next step

Pick based on priority — none of these is committed to:

1. **`held_action.approve` → `executed`** — the next Appendix D consequential operation (`calendar.write` remains the named likely candidate) is its real trigger. Needs a real idempotency contract for the target adapter before declaring `commit_mode="redrive"` (ADR-001's amendment gate).
2. **Retry-with-backoff for jobs** — D014's other named, still-unbuilt "supervised task" property. Worth its own real design conversation, separate from timeout (they're related but distinct — a retry policy needs to decide backoff shape, how it interacts with the existing 3-consecutive-failure quarantine, and whether it's per-slot or per-job).
3. **Watch the next few real automation cycles** — automation is genuinely live now (§1); worth a spot-check in a week or two that `morning_plan`/`deadline_sweep` are still firing cleanly, no `job.overrun`/`job.quarantined` accumulating, before treating "it's on" as a closed question.
4. **CSS/visual polish on the transition buttons** — still functional, minimally styled. Not urgent.
5. Something else entirely — Know/Chat both still blocked on Phase 2/Phase 3 architecture that doesn't exist yet.

Before doing real work: run `git status`, `git log --oneline -15`, the full test suite, and check whether the real Core needs a restart (compare its live `registry.get` operation count, `system.health` job list, and — now that automation is genuinely live — its real `job_run` history for anything unexpected, against `%KANG_HOME%/core.lock` actually being held by the process you think is running it). Don't assume this handoff is still accurate by the time you read it, and don't assume "it's running" means "it has today's code" — the 2026-08-11 handoff's own hard-won lesson (a Core silently missing its entire scheduler config for the project's whole life) is exactly the class of thing that only shows up when checked directly, not assumed.
