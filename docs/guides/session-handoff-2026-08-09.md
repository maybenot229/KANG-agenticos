# Session handoff — 2026-08-09

Everything below was verified against the actual repo state at handoff time (git log, a fresh full test run, a fresh lint run, fresh UI typecheck/build/test, and the real running Core's own `registry.get`) — not recalled from memory or from the prior handoff. This supersedes `session-handoff-2026-08-08.md`, which this session picked up from at commit `cf80e88`.

---

## 1. State (verified just now)

```
git status --porcelain            → (empty — clean working tree)
git rev-list --count origin/main..HEAD → 0 (everything pushed)
python -m pytest tests/unit tests/suites tests/integration -q → 754 passed
ruff format --check src tests tools cli   → 281 files already formatted
ruff check src tests tools cli            → All checks passed!
lint-imports --config tools/importlinter.toml → Contracts: 8 kept, 0 broken
python tools/lint_sizes.py src            → 0 hard violation(s), 53 soft warning(s)
python tools/lint_banned_patterns.py src  → 0 violation(s)
python tools/lint_tree_hygiene.py .       → 0 violation(s)
python tools/build_root_docs.py --check   → CLAUDE.md is current.
cd ui && npm run typecheck && npm run build && npm run test → all clean, 56/56 UI tests
```

`main` is at `d9bd097`, fully pushed — **nothing local, nothing unpushed.**

**The real, persistent Core is running right now**, restarted at the end of this session specifically so it would pick up today's code — confirmed via its own `registry.get`: **36 operations live**, including everything built today (`task.complete`, `milestone.reach`/`.miss`/`.drop`, `goal.achieve`/`.revise`/`.retire`, `project.complete`). The Core that had been running most of the session (PID 9056, started 4:17 PM, before almost all of today's work) was stale — confirmed directly (28 ops, none of today's new ones) before being replaced. **If you find KANG behaving like an older version, check whether the Core needs a restart — `tools/kang_start.ps1` handles this safely (it detects an already-live Core and won't double-launch).**

### Commits landed this session (chronological)

```
96c4ac5 ci(ui): wire the registry->TS client generator into CI (ADR-011 gap)
dcd8c52 feat(M5): goal domain — tracking only (ADR-016, standing pattern)
745e703 feat(ui): palette "New project…"/"New competition…" commands
6a81879 feat(ui): goal's UI home — a Goals section in PlanScreen
6480b87 tools: minimal manual launcher for daily use (kang_start.ps1)
e20e661 feat(M4/M5): task.complete - the task entity's first status transition
e70e12f feat(ui): "Done" on Today's Quests; fix the launcher's connection-refused bug
77d7401 fix(kernel): serve() actually runs the scheduler's boot catch-up (D014)
9bc982d feat: start-at-login (ADR-017, activates 03_ROADMAP §8's RESERVED row)
6a38b22 feat(M5): milestone.reach/.miss/.drop (ADR-018)
1c737ff feat(M5): goal.achieve/.revise/.retire (ADR-018)
2b834a1 feat(M5): project.complete (ADR-018) - accept
452ab4b fix(tools): kang_start.ps1's own rebuild instructions were wrong
d9bd097 test(ui): ProjectsScreen -> ProjectDetail click-through (ADR-015's own named gap)
```

Registry is now at **36 operations**, contract version 1 (was 26 at the last handoff). ADR count: **18** (001–018), all accepted except two pre-existing, unrelated to this session: ADR-008 (single-instance enforcement, core-side half) and ADR-011... wait, ADR-011 status — see note below. All four new ADRs this session (016, 017, 018 — 015 was already accepted last session) reached `accepted`, reviewed against real code and a fresh test run before flipping, not rubber-stamped.

**Correction to the last handoff's own numbering**: it said ADR count 15 (001–015); this session added 016 (goal.created, standing pattern), 017 (start-at-login), 018 (status-transition standing pattern) — three new ADRs, all accepted.

---

## 2. What's actually built now

Everything below is **live-verified** at least once this session — real Core, real HTTP, and for the desktop app itself, the actual native Tauri window on the actual desktop, not just the browser-pane dev loop.

- **`goal` domain (ADR-016)** — `goal.create`/`.list`, the fourth instance of the `project`/`competition`/`milestone.created` pattern, this time backed by a standing ADR instead of a fourth near-identical one. `goal_service.py` lives inside `domain/projects/` (that package's own `__init__.py` already named "Projects, milestones, goals" as one cluster). A UI home was found for it — a Goals section in `PlanScreen` (not a new top-level domain; `goal` doesn't have one of 09_UI's seven fixed spokes).
- **Palette gained "New project…"/"New competition…" commands** — `formOpen` lifted to `App.tsx` for both screens, mirroring `deadlineFormOpen`'s own precedent. Deliberately NOT added: "New milestone…" (needs a project already selected — no picker in the palette) and "New goal…" at the time (goal had no UI surface yet when this landed; it does now, via PlanScreen, but the palette command was never revisited — a small follow-up, not urgent).
- **CI's `ui` job was red on every real run since it was added** — found by reading a pasted GitHub Actions failure, not assumed. Root cause: `ui/src/generated/` (ADR-011's generated TS client) is gitignored; CI never ran the generation step, only local dev's stale on-disk files ever worked. Fixed: `ci.yml`'s `ui` job now sets up Python and runs `python tools/generate_ts_client.py && npm run generate` before typecheck/build/test.
- **A minimal manual launcher** (`tools/kang_start.ps1`) — starts the real Core against the real, persistent `%KANG_HOME%`, waits for the session handshake, launches the shell. Gained a pre-flight liveness check later in the session (checks whether a Core is already answering before starting a second one).
- **`task.complete`** — the task entity's first status-transition operation. Unlike everything built after it, the store/domain layers already existed (`TaskStore.update()`, `complete_task()`), fully tested, just never wired to an API operation. Real bug fixed in `complete_task()` along the way: it stamped `completed_at` but never `updated_at`, latent until this was its first real caller.
- **"Done" button on Today's Quests** — the first place completing anything is possible anywhere in the app. Click it, `task.complete` fires, the quest disappears from the list on re-fetch.
- **The launcher's actual desktop-rendering bug, found and fixed twice** — first pass: the debug build expects Vite's dev server at `localhost:1420`; switched to a release build. Second pass, found live on the user's own screen after a routine rebuild: a **plain `cargo build --release` silently no-ops on this Tauri project** — it doesn't reliably run `tauri.conf.json`'s `beforeBuildCommand` or trigger the devUrl-vs-embedded-assets codegen, so it can produce a binary that still points at the absent dev server. The real fix is `cargo tauri build --no-bundle`, confirmed by the compile time alone (2m24s of real work vs. the bogus build's suspicious &lt;2s no-op). **Both of this session's own earlier "fixed" claims for this bug were wrong** — the first was never actually re-verified visually; only the second, checked against the user's real screen, is trustworthy. `kang_start.ps1`'s own header comment now names the correct command.
- **`serve()` now runs the scheduler's boot catch-up (D014)** — `Scheduler.catch_up()` had been fully built and tested since M3 but never called anywhere in the real boot path; confirmed by direct code read, not assumed. Deliberately scoped small: one call before the operation channel accepts requests, not a continuous tick loop (that needs a supervised-task primitive that doesn't exist yet — 11_CODING §25 bans unsupervised threads) and not wiring `deadline.sweep` as an automatic job (would need a new permission grant, its own ADR).
- **Start-at-login (ADR-017)** — activates a RESERVED roadmap row. A Windows Startup-folder shortcut, registered on the user's real machine, runs `kang_start_hidden.vbs` → `kang_start.ps1` with no visible window at every login. The one new risk this introduces (a forgotten-already-running Core plus a habitual re-launch) is closed by the same pre-flight guard named above.
- **`milestone.reach`/`.miss`/`.drop`, `goal.achieve`/`.revise`/`.retire`, `project.complete` (ADR-018)** — six new status-transition operations across three entities, one standing ADR instead of three (or six) near-identical documents. Unlike `task.complete`, none of the store/domain layers existed for these — built the full stack per entity (port `get`/`update`, SQLite + fake adapters, domain transition functions, `.updated` event registration, API schemas/handlers/registry entries, composition wiring). `project` deliberately got only `complete` (not the full five-status graph) — no prior document names a project verb set the way milestone/goal's ADRs did, and building `pause`/`.resume`/`.archive`/`.abandon` with no named consumer would be exactly the speculative-structure pattern this project rejects everywhere else.
- **`_build_handlers` split** — crossed the size lint's 80-line hard limit the moment `goal`'s transitions landed; split into `_build_project_cluster_handlers` (project/competition/milestone/goal — the four entities `domain/projects/`'s own package grouping already treats as one cluster), not a relaxed limit.
- **`ProjectsScreen` → `ProjectDetail` UI test** — the one named gap left from the 2026-08-07 session (ADR-015), closed: the click-through, the milestone fetch it triggers, and the back button all covered.
- **The desktop app is genuinely resident now** — tray icon (fixed a prior session), the launcher, boot catch-up, and start-at-login compose into something that behaves like D016's real run model for the first time, not a manually-driven demo.

### Learn domain: investigated, confirmed not ripe — nothing built

Checked from three independent angles, not just trusted the UI stub's own claim: `03_ROADMAP.md` names spaced repetition explicitly under **Phase 3 (v0.3)**, grouped with the Tutor agent and dependent on Phase 2 memory (unbuilt); no migration creates `quiz_result`/`repetition_item` (documented in `07_DATABASE.md`, never migrated — a step further behind than `goal` was, which at least had real schema waiting); the PRD tags both relevant requirements (FR-042, FR-092) as version 0.3 explicitly. Even the "tracking only, no AI" angle that worked for `goal` doesn't apply — the roadmap has already ruled on the version. **Not ripe. Don't build it until Phase 2/3 context exists** — same verdict shape as the `held_action.approve` investigation from the prior session.

---

## 3. Architectural notes worth knowing

- **`domain/ports/{project,milestone,goal}_store.py` all gained `get()`/`update()` this session** — none had them before (only `task`/`deadline` did). Each store's constructor now takes `clock` (needed for `update()`'s `updated_at` stamp) — every call site was updated, including `composition.py` and every test file that constructed one directly.
- **The recovery appliers for project/milestone/goal were already upsert-shaped from the day they were written** (handling both insert and update branches) — only `.created` was registered driving them until this session. Registering `.updated` for all three needed zero new applier code, only three new dispatch-table entries.
- **`ui/src/generated/` and `ui/registry.snapshot.json` are gitignored build artifacts** — regenerate with `python tools/generate_ts_client.py && cd ui && npm run generate` after any registry change, and rebuild the shell (`cargo tauri build --no-bundle`, NOT plain `cargo build --release`) before expecting the desktop app to reflect it. CI now does this automatically; local dev does not.
- **The real, persistent Core process is stale the instant new backend code lands** — Python doesn't hot-reload. `tools/kang_start.ps1`'s pre-flight guard prevents a *second* Core, but does nothing to detect a *stale* one still answering fine on old code. If a session lands backend changes, restart the Core before calling anything "live" — this session found out the hard way (see §1) that "the process is running" and "the process has today's code" are different claims.
- **ADR-011's own RESERVED-retirement line in `03_ROADMAP.md`** was never actually removed even though the generator landed and CI now runs it — worth a look next time someone is in that document; not touched this session because ADR-011 itself is still `proposed` (awaiting Kang's review, per its own author's note), and the row's stated retirement condition is "once ADR-011 is accepted and lands," not just "the code exists."

---

## 4. Known, named, real gaps — not forgotten, deliberately not built

1. **`held_action.approve` → `executed`** — still blocked, per the 2026-08-08 investigation (re-confirmed not touched this session): no real consequential operation exists yet to drive it.
2. **No continuous scheduler tick loop** — boot catch-up runs once at startup; nothing re-checks for newly-due jobs while the process stays running. Needs a supervised-task primitive that doesn't exist in this codebase yet.
3. **`deadline.sweep` isn't wired as an automatic job** — the operation is real and tested; making it fire hourly needs a new `kernel:scheduler` permission grant (an authority-path change, its own ADR).
4. **`project.pause`/`.resume`/`.archive`/`.abandon`** — real enum values, zero operations, deliberately (ADR-018's own scope ruling).
5. **No UI for `milestone.reach`/`.miss`/`.drop`, `goal.achieve`/`.revise`/`.retire`, or `project.complete`** — all six are API-only right now, reachable by curl but not by clicking anything. `task.complete` is the only transition with a real UI entry point (Today's Quests' "Done" button).
6. **Palette has no "New goal…" command** — `goal` gained a real UI home (PlanScreen) after the palette commands were built; never revisited.
7. **ADR-008's core-side single-instance lock** — still RESERVED, unbuilt. The shell half is real (`tauri_plugin_single_instance`); the Core half is only narrowly worked around (the pre-flight liveness check in `kang_start.ps1`), not actually fixed.
8. **No real D016 packaged installer** — start-at-login is a per-user Startup-folder shortcut registered by hand, not part of any installer. Auto-updater, staged migrations-on-copy, and the rest of D016's deployment story remain unbuilt.
9. **Learn/Know/Chat** — Learn confirmed not ripe this session (§2 above); Know and Chat still need real scoping conversations, both blocked on bigger unbuilt pieces (memory architecture, the AI phase).

---

## 5. Working discipline this session actually followed (keep doing this)

- **Verified the prior handoff's claims fresh rather than trusting them** — ran the full test suite and every lint before touching anything, confirmed the snapshot matched exactly (667 passed, matching the handoff's own number) before starting real work.
- **Investigated before building, twice, and both times the honest answer was "not yet"** — Learn (this session) and the held_action re-confirmation, same discipline as the 2026-08-08 session's own held_action investigation: read the real constraints, don't build ahead of them.
- **Wrote standing ADRs instead of near-identical repeats, twice** — ADR-016 (`.created` pattern, applied to `goal`) and ADR-018 (`.updated` pattern, applied to all three of milestone/goal/project at once) — both explicitly following the precedent the prior ADR itself flagged ("if a fourth entity needs this, consider a standing ADR").
- **Caught and corrected two of its own wrong claims, live, against the user's real screen** — the `cargo build --release` bug was declared fixed twice before it actually was; the second correction is the one that held, verified against a screenshot the user took, not assumed from a process-alive check.
- **Live-verified every backend feature against a real throwaway Core** — task completion, scheduler boot catch-up (with a real simulated 3-day-downtime backdate), and all three entities' status transitions, each time creating real rows, checking real `change_log`/audit output, then cleaning up.
- **Never left the real persistent Core running stale code without saying so** — found and fixed the staleness at the very end of the session rather than writing a handoff describing features that weren't actually live.
- **Commit per coherent slice, real messages via `git commit -F <file>`, never inline `-m`** — held all session.
- **Never pushed without explicit instruction** — held all session; pushed only when asked, several distinct times, always after a fresh full test run first.
- **Cleaned up every throwaway `KANG_HOME` and background process** — via `Get-CimInstance`/`Stop-Process` (PowerShell), matching the prior session's own established Windows-process-cleanup discipline.

---

## 6. Next step

Pick based on priority — none of these is committed to:

1. **UI wiring for the six new transitions** — `ProjectDetail` for milestone reach/miss/drop, `ProjectsScreen` for project.complete, the new Goals section in `PlanScreen` for goal achieve/revise/retire. The single biggest gap between "the backend can do it" and "Kang can actually use it."
2. **Palette "New goal…"** — small, now that goal has a real UI home.
3. **The continuous scheduler tick loop** — needs a design decision first (the supervised-task primitive), not just code. Worth a real conversation before starting.
4. **`deadline.sweep` as an automatic job** — needs its own small ADR (the new `kernel:scheduler` scope grant) before any code.
5. **ADR-008's core-side single-instance lock** — the real fix for the risk `kang_start.ps1`'s pre-flight guard only narrowly works around.
6. Something else entirely — Know/Chat still need real scoping conversations, per §4 item 9.

Before doing real work: run `git status`, `git log --oneline -15`, the full test suite, **and check whether the real Core needs a restart** (`registry.get` against the real session — compare its operation count to the registry snapshot) — don't assume this handoff is still accurate by the time you read it, and don't assume "it's running" means "it has today's code." Same discipline it was written with.
