# Session handoff — 2026-08-11

Everything below was verified against the actual repo state at handoff time (git log, a fresh full test run, a fresh lint run, fresh UI typecheck/build/test, and the real running Core's own `registry.get`/`system.health`) — not recalled from memory or from the prior handoff. This supersedes `session-handoff-2026-08-10.md`, which this session picked up from at commit `8c707e8`.

---

## 1. State (verified just now)

```
git status --porcelain                    → (empty — clean working tree)
git rev-list --count origin/main..HEAD    → 0 (everything pushed)
python -m pytest tests/unit tests/suites tests/integration -q → 776 passed
ruff format --check src tests tools cli   → 290 files already formatted
ruff check src tests tools cli            → All checks passed!
lint-imports --config tools/importlinter.toml → Contracts: 8 kept, 0 broken
python tools/lint_sizes.py src            → 0 hard violation(s), 54 soft warning(s)
python tools/lint_banned_patterns.py src  → 0 violation(s)
python tools/lint_tree_hygiene.py .       → 0 violation(s)
python tools/build_root_docs.py --check   → CLAUDE.md is current.
cd ui && npm run typecheck && npm run build && npm run test → all clean, 62/62 UI tests
```

`main` is at `06a0b63`, fully pushed — **nothing local, nothing unpushed.**

**The real, persistent Core is running right now, restarted twice this session** — first to pick up ADR-019's tick-loop code, again after this session's own permissions/config fixes below — **PID 24332, started 2026-08-11 22:26:11 PM**, confirmed via its own `registry.get` (36 operations, unchanged — neither ADR added a new operation) and `system.health` (both `morning_plan` and `deadline_sweep` registered, zero consecutive failures). It is holding the real `%KANG_HOME%/core.lock` (confirmed: a direct `msvcrt.locking()` acquire attempt from outside the process fails with `PermissionError`, the expected mandatory-lock behavior on Windows, same check the 2026-08-10 handoff used).

### Commits landed this session (chronological)

```
fa7bfb6 feat(kernel): continuous scheduler tick loop (ADR-019) - accept
06a0b63 feat(kernel): deadline.sweep wired as an automatic job (ADR-020) - accept
```

Two commits, both design-conversation-then-build-then-live-verify. ADR count: **20** (001–020), up from 18. Both new ADRs went straight to `accepted` in the same session they were filed — both were narrow, mostly-mechanical increments over already-decided mechanisms (ADR-006's job→operation dispatch), not open-ended designs.

---

## 2. What's actually built now

Both live-verified against real running Cores (never the real persistent one for anything destructive — throwaway `%KANG_HOME%`s for all backend proving, the real one only restarted/reconfigured deliberately at the end of each).

- **ADR-019 — the continuous scheduler tick loop.** `Scheduler.catch_up()` used to run exactly once, at boot; nothing re-checked for newly-due jobs while the process stayed running. The actual obstacle turned out to be DB-001, not the absence of a loop: `kang.db`'s connection is thread-confined (`sqlite3`'s default `check_same_thread`), and the HTTP server is deliberately single-threaded so all requests stay on the connection-owning thread — a naive background-thread timer would have either crashed or needed a second write connection, breaking the single-writer invariant. The fix reuses `socketserver.BaseServer.serve_forever`'s existing `service_actions()` hook — called once per poll cycle, on the exact thread that already owns `kang.db` — to re-run `Scheduler.tick()` (a thin wrapper that catches and audits, as `automation.tick_failed`, any failure `catch_up()` doesn't already isolate per-job) every `TICK_INTERVAL_S` (60s, a plain constant). No new thread, no new connection, no new primitive. **Live-verified**: a real, continuously-running (never restarted) throwaway Core was given a job due only after boot; a `job_run` row appeared at the exact slot with `outcome='ok'`, proving the live tick — not a subsequent boot — picked it up.
- **ADR-020 — `deadline.sweep` wired as an automatic job.** `deadline.sweep` (FR-031, tested since M3) had never been invoked by anything but manual API calls. 05_AGENTS Appendix E already specified its cadence (`hourly`, any product state, `run_once_latest`); ADR-006 already specified the wiring mechanism. The only real trigger was the permissions grant: the operation requires scope `deadlines.mark_alerted`, which `kernel:scheduler` didn't hold — an authority-path change, hence its own small ADR. Wired identically to `morning_plan`: a second `Job` row registered in `_wire_scheduler`, `JOB_OPERATIONS["deadline_sweep"] = "deadline.sweep"`, one line added to `permissions.toml`. No new scheduler mechanism — `_catch_up_job`/`Scheduler.tick()` already iterate every registered job, so the second job was handled for free, which is itself proof ADR-006's mechanism actually generalizes past its first instance. **Live-verified**: a real subprocess test backdates `deadline_sweep` 3 hours and asserts `outcome='ok'` against the real `permissions.toml`/`kang.toml`, plus a manual throwaway-`%KANG_HOME%` boot confirming `system.health` surfaces both jobs correctly.
- **A real design conversation preceded both builds**, same discipline as every prior session: read ADR-006, D014, 11_CODING §25, DB-001, 05_AGENTS Appendix E directly before drafting either ADR — not reasoned from a summary. ADR-019 had a genuine open fork (which background-execution primitive); ADR-020 did not (05 Appendix E and ADR-006 had already decided everything except the one-line grant), and was scoped and drafted accordingly — a smaller ADR for a smaller decision, not padded to look more substantial.

---

## 3. Two real production-environment gaps found and fixed this session (not code bugs — environment drift)

Found while restarting the real Core for ADR-019/020, surfaced to Kang before touching anything, fixed only after explicit confirmation each time:

1. **`permissions.toml` drift.** The real `%KANG_HOME%/config/permissions.toml` predated ADR-015 and ADR-016 — it was missing the `kernel:milestones`/`kernel:goals` grants those already-accepted ADRs decided. Confirmed by direct diff against the shipped default, and confirmed `goal_ops.py`/`milestone_ops.py` really do publish under those exact principals (not a vestigial/unused grant). **Real impact:** creating a milestone or goal through the real running app would have failed with `PermissionDenied` — never actually hit yet (`kang.db` has zero milestone/goal rows; all milestone/goal dev work happened against throwaway Cores). **Fixed:** the real file now matches the shipped default exactly (byte-for-byte diffed to confirm) — all three missing grants (`kernel:milestones`, `kernel:goals`, `kernel:scheduler`'s new `deadlines.mark_alerted`) applied in one pass.
2. **`kang.toml` had never existed in the real `%KANG_HOME%`.** Confirmed by directory listing (`config/` held only `permissions.toml`) and the audit log: **10 `automation.unconfigured` entries** — every single boot across this whole multi-day project, including the ADR-008/017/019 restarts, had `core.scheduler = None`. Automation has never actually run against the real Core before today. **Fixed, with explicit confirmation asked and given before doing it** (this is a real behavior change, not a mechanical sync): the shipped default `kang.toml` (Kang's real routine per the 2026-07-19 intake — `Asia/Kuching`, 05:45/06:45) was copied in. `morning_plan` and `deadline_sweep` are now both genuinely live for the first time — confirmed via `system.health`, and confirmed the boot did NOT add an 11th `automation.unconfigured` entry.

**Kang should know:** `morning_plan` will fire for real tomorrow at 05:45 local, and `deadline_sweep` runs hourly starting from this boot. This is the first time either has executed outside a throwaway test environment.

---

## 4. Architectural notes worth knowing

- **`service_actions()` is now the tick mechanism** — `http_binding.py::make_server` gained one `server_class` parameter (stays fully scheduler-ignorant); `composition.py::serve()` builds a small `HTTPServer` subclass closing over `core.scheduler`/`core.clock`. `Core` gained a `clock` field so `serve()` can time the interval gate (never wall time directly — 11 §25).
- **Two jobs now share one `Scheduler` instance** — `_catch_up_job`, `tick()`, and quarantine logic needed zero changes to handle a second job, which is itself the evidence that ADR-006's job→operation mechanism generalizes rather than having been narrowly built for `morning_plan` alone.
- **`JOB_OPERATIONS` is now a two-entry table** (`composition.py`) — still the one plain, greppable literal SEC-005/P5 ask for; still the composition root's own job, per ADR-006 ruling 4.
- **CLAIMS.md's own forward-pointer discipline held**: the 2026-08-09 boot-catch-up claim named both gaps ("a continuous tick loop... " and "wiring `deadline.sweep`...") as explicitly deferred; both notes were edited in place this session to point forward to the ADR that closed them (ADR-019, ADR-020), rather than left stale or silently deleted.

---

## 5. Known, named, real gaps — not forgotten, deliberately not built

Unchanged from the 2026-08-10 handoff except items 2 and 3, closed this session:

1. **`held_action.approve` → `executed`** — still blocked; unchanged this session, not touched.
2. ~~**No continuous scheduler tick loop**~~ — **closed this session (ADR-019).**
3. ~~**`deadline.sweep` isn't wired as an automatic job**~~ — **closed this session (ADR-020).**
4. **`project.pause`/`.resume`/`.archive`/`.abandon`** — unchanged, not re-examined this session.
5. **No real D016 packaged installer** — unchanged, not re-examined this session.
6. **Learn/Know/Chat** — unchanged, not re-examined this session.
7. **`job.timeout_s`/retry-with-backoff enforcement** — explicitly named, explicitly NOT addressed by either ADR this session (both said so in their own Consequences). A hung job body still hangs whichever tick calls it; 05 Appendix E's "2m timeout, 2 retries" for `deadline_sweep` remains unenforced. Needs a real mechanism for interrupting an in-flight call — separate, real work.
8. **Event-triggered job admission** (`schedule = 'event:{type}'`) — confirmed by direct grep this session: `Schedule.is_event_triggered` is defined but consumed nowhere. Parsed, unwired. Not touched by ADR-019 (which only re-triggers `catch_up()`, itself blind to event-triggered schedules) or ADR-020 (`deadline_sweep` is a plain interval schedule).

---

## 6. Working discipline this session actually followed (keep doing this)

- **A real design conversation before building, twice** — ADR-019 had a genuine open fork (background-execution primitive vs. the existing `service_actions()` hook) surfaced with options and trade-offs, not assumed; ADR-020 was correctly recognized as *not* having an open fork (05 Appendix E + ADR-006 had already decided everything but the grant) and scoped/drafted proportionally smaller — not padded to look like more of a decision than it was.
- **Read the actual constraint, not the surface symptom** — the tick loop's real obstacle was DB-001's thread confinement, found by reading `connection.py` and `http_binding.py` directly, not just composition.py's own docstring naming "a supervised-task primitive that doesn't exist."
- **Live-verified both ADRs against real running Cores**, never just unit tests — ADR-019 via a continuously-running (never restarted) throwaway Core proving the *live* tick fired a newly-due job; ADR-020 via both a real subprocess replay test and a manual throwaway boot.
- **Found real environment drift by checking, not assuming** — diffing the real `permissions.toml` against the shipped default (rather than assuming a prior session had kept them in sync) surfaced a genuine latent bug (`kernel:milestones`/`kernel:goals` missing); checking for `kang.toml`'s actual existence (rather than assuming "the Core is configured because it's running") surfaced that automation had never once been live.
- **Surfaced both findings before fixing, asked before the behavior-changing one** — the permissions sync was framed as "these are already-decided ADRs, just never synced" and proceeded on a general "yes, proceed"; turning on `kang.toml` for the first time was explicitly separated out and confirmed on its own, because it's a real behavior change (automation actually running against Kang's real life for the first time), not a mechanical fix.
- **Commit per coherent slice, real messages via `git commit -F <file>`, never inline `-m`** — held all session.
- **Never pushed without explicit instruction** — held; pushed only when asked, after a fresh full test run each time.
- **Restarted the real Core specifically because new backend code or config landed** — twice this session, each time confirmed live via `registry.get`/`system.health` and the lock genuinely held before moving on.
- **Cleaned up every throwaway `%KANG_HOME%` and process** — PowerShell `Get-Process`/`Stop-Process` used throughout (more reliable than Bash's `ps`/`kill` for native Windows processes, per established guidance).

---

## 7. Next step

Pick based on priority — none of these is committed to:

1. **`held_action.approve` → `executed`** — the next Appendix D consequential operation (`calendar.write` remains the named likely candidate) is its real trigger, per the 2026-08-10 session's own sharpened verdict. Needs a real idempotency contract for the target adapter before declaring `commit_mode="redrive"` (ADR-001's amendment gate).
2. **`job.timeout_s`/retry-with-backoff enforcement** — now that two real jobs are live and unenforced timeouts are a real (if still unlikely) operational risk rather than a theoretical gap, this may be worth a design conversation sooner than before. Needs its own real conversation — what "interrupting an in-flight call" means in this codebase hasn't been designed at all yet.
3. **CSS/visual polish on the transition buttons** — still functional, minimally styled. Not urgent.
4. **Watch the first real automation cycles** — `morning_plan` fires tomorrow 05:45 local, `deadline_sweep` hourly from this boot. Worth confirming for real (via `system.health`/audit log) that the first live firings actually happened as expected, not just trusting the wiring.
5. Something else entirely — Know/Chat both still blocked on Phase 2/Phase 3 architecture that doesn't exist yet.

Before doing real work: run `git status`, `git log --oneline -15`, the full test suite, and check whether the real Core needs a restart (compare its live `registry.get` operation count and `system.health` job list against what's expected, and whether `%KANG_HOME%/core.lock` is actually held by the process you think is running it) — don't assume this handoff is still accurate by the time you read it, and don't assume "it's running" means "it has today's code" **or "it's actually configured."** This session's own biggest finding was that "the Core is up" had silently meant "automation has never once been on" for the entire project's life — check state directly, every time, same discipline this handoff was written with.
