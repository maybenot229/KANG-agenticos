# Session handoff — 2026-08-10

Everything below was verified against the actual repo state at handoff time (git log, a fresh full test run, a fresh lint run, fresh UI typecheck/build/test, and the real running Core's own `registry.get`) — not recalled from memory or from the prior handoff. This supersedes `session-handoff-2026-08-09.md`, which this session picked up from at commit `b777127`.

---

## 1. State (verified just now)

```
git status --porcelain            → (empty — clean working tree)
git rev-list --count origin/main..HEAD → 0 (everything pushed)
python -m pytest tests/unit tests/suites tests/integration -q → 768 passed
ruff format --check src tests tools cli   → 289 files already formatted
ruff check src tests tools cli            → All checks passed!
lint-imports --config tools/importlinter.toml → Contracts: 8 kept, 0 broken
python tools/lint_sizes.py src            → 0 hard violation(s), 54 soft warning(s)
python tools/lint_banned_patterns.py src  → 0 violation(s)
python tools/lint_tree_hygiene.py .       → 0 violation(s)
python tools/build_root_docs.py --check   → CLAUDE.md is current.
cd ui && npm run typecheck && npm run build && npm run test → all clean, 62/62 UI tests
```

`main` is at `e0cffd6`, fully pushed — **nothing local, nothing unpushed.**

**The real, persistent Core is running right now, restarted this session specifically to pick up the startup-lock code** — PID 12308, started 01:00:41 AM, confirmed via its own `registry.get`: **36 operations live.** It is holding the real `%KANG_HOME%/core.lock` (confirmed: attempting to read the file while it runs returns "Device or resource busy," the expected mandatory-lock behavior on Windows). The 2026-08-09 handoff's own warning bears repeating, now with a real enforcement mechanism behind it: **the real Core is stale the instant new backend code lands — Python doesn't hot-reload.** `tools/kang_start.ps1` now has two independent layers protecting against a stale-vs-fresh double-launch mix-up: its own pre-flight HTTP liveness check (fast path, friendly message), and — new this session — a real OS-level lock that makes a genuine second Core impossible regardless of launch path, not just the shell's own launch path.

### Commits landed this session (chronological)

```
5947758 feat(ui): wire the six status transitions into the UI
e0cffd6 feat(kernel): core-side single-instance lock (ADR-008 Part A2) - accept
```

Two commits — a short session, both substantial. ADR count: **18** (001–018), same as the last handoff — no new ADR numbers this session, but **ADR-008 flipped from `proposed` to `accepted (w/ amendment)`**, its first status change since 2026-07-29. Registry unchanged at **36 operations** (this session added no new operations — the transitions UI work wired existing ones into screens; the startup lock touches no operation at all, it's pre-operation-channel process lifecycle).

---

## 2. What's actually built now

Both live-verified — the transitions UI in a real browser against a real throwaway Core (every button clicked, every real row checked in `kang.db` afterward), the startup lock via two genuine `python -m kang.kernel.runtime.composition` subprocesses racing for the same real `%KANG_HOME%`.

- **The six status transitions (built 2026-08-09) are now reachable by clicking, not just curl.** `PlanScreen`'s Goals section gained Achieve/Revise/Retire (active goals only — the transitions reject any other starting status, so the buttons only appear where they'd succeed). `ProjectDetail` gained Reach/Miss/Drop per pending milestone and a Complete button for the project itself (deliberately placed in the detail view, not on `ProjectsScreen`'s list row — see `ProjectDetail.tsx`'s own docstring for why a nested action button on a full-row navigation target wasn't the right call). All three follow the exact shape `task.complete`'s "Done" button already established: fresh idempotency key, re-fetch on success, disable the clicked control while in flight. **Live-verified in a real browser** (Vite dev server against a real throwaway Core via the `VITE_DEV_SESSION_*` env-var path `ui/src/api/session.ts` documents) — watched each transition fire for real: a goal flipped to "achieved" and its buttons vanished, a milestone flipped to "reached," a project's Complete button closed the detail view and the list re-rendered showing "completed."
- **A design conversation, then a build, on four longer-standing gaps.** Before touching code, a real design pass (reading the actual constitution, not a summary of it) ruled on `project.pause`/`.resume`/`.archive`/`.abandon` (not ripe, no ADR — no lived instance of the need yet), `held_action.approve → executed` (not ripe as its own ADR; the design is already settled, the next Appendix D operation's own ADR inherits it directly), Learn/Know/Chat (Learn stays closed; Know/Chat scoping itself is premature — a document with no Phase 2 memory architecture underneath it to constrain it would mostly be guessing), and the D016 packaged installer (not ripe in full — not enough surface area to package yet — but surfaced one real, smaller, already-specified increment: **ADR-008 Part A2**, deferred since July because no real core startup sequence existed to attach it to. One did, as of the prior day's boot-catchup work).
- **ADR-008 Part A2 — the core-side startup lock — built, exactly as the ADR already specified, nothing re-decided.** `domain/ports/startup_lock.py` (the port), `adapters/os_windows/startup_lock.py` (`FileStartupLock`, an exclusive `msvcrt.locking()` region on `%KANG_HOME%/core.lock` — Windows-only code correctly confined behind the port, satisfying NFR-010 at the port boundary rather than by the adapter itself being portable), `adapters/fakes/startup_lock.py` (`FakeStartupLock`, deliberately takes a *shared* dict so two fake instances can genuinely contend the way two OS processes would). `composition.py::build_core()` acquires the lock before opening `kang.db` or the eventlog — a failure anywhere after acquisition releases it before propagating (split into `_build_core_locked` to keep that bracket readable). `Core.close()` releases it. `serve()` catches `AlreadyRunningError`, reports one clean line to stderr, exits 1 — no raw traceback, no silent second scheduler racing the first.
- **A real, useful finding from testing it for real:** Windows file locking is mandatory, not advisory — a second process can't even *open-and-read* a locked byte range, not just fail to write it. One test's own assertion had to move from "read the file while the lock is held" to "read it after release" — the exclusivity claim was never in doubt (11 other contract-suite assertions proved it cleanly), only that specific diagnostic-content check was wrong about what Windows allows a bystander to do mid-hold.

---

## 3. Architectural notes worth knowing

- **`tests/integration/os_windows/` now has its first real test file.** `17_PROJECT_STRUCTURE.md` named this directory (alongside sqlite/eventlog/obsidian/providers) as "per real technology" long before anything in `adapters/os_windows/` had a real OS-level mechanism to prove against — the tray and notifications-port items it also names are shell-side or unbuilt. `test_startup_lock.py` is the first tenant.
- **A shared port-contract suite pattern was used for a genuinely new-shaped port.** `tests/fixtures/startup_lock_contract.py` mirrors `task_store_contract.py`'s own "one suite, run against fake and real identically" precedent — but unlike a store contract (create/get/update on isolated rows), this one's whole point is *cross-instance contention*, so the fixture shape (`make_lock` factory bound to the *same* underlying lock across calls) had to be designed for that specifically, not just copied.
- **`Core` gained a `startup_lock` field and `close()` now releases it** — every existing caller of `build_core()`/`Core.close()` (roughly a third of the test suite) needed zero changes, because the field defaults to `None` and `close()` guards on that. The 768-tests-still-green number after this landed is the actual proof that held, not an assumption.
- **`build_core()` is now two functions**, `build_core()` (acquire-lock-then-delegate-or-release-on-failure) and `_build_core_locked()` (everything that used to be `build_core()`'s body) — a plain extraction for the try/except bracket's own readability, not a new concept, same reasoning `_build_stores`/`_build_bus_wiring` were extracted for earlier this week.
- **ADR-008 was amended in place, not rewritten** — its original Part A2 text ("NOT YET IMPLEMENTABLE... register as a RESERVED entry") stays exactly as written, with a new "A2 implementation (2026-08-10)" section appended below it, per ADR-001's own established amendment precedent. The RESERVED row itself is removed from `03_ROADMAP.md` §8 (implemented, not merely triggered) — same retirement pattern ADR-017 used for the start-at-login row.

---

## 4. Known, named, real gaps — not forgotten, deliberately not built

Unchanged from the 2026-08-09 handoff except item 7, closed this session:

1. **`held_action.approve` → `executed`** — still blocked; this session's own design pass re-confirmed it (verified `held_action_store.create()` is never called anywhere outside tests, directly in the code, not from memory) and sharpened the trigger: the next Appendix D operation's own ADR inherits ADR-001/002 directly, no separate `held_action`-specific ADR is meant to exist at all.
2. **No continuous scheduler tick loop** — boot catch-up runs once at startup; nothing re-checks for newly-due jobs while the process stays running. Still needs a supervised-task primitive that doesn't exist in this codebase yet.
3. **`deadline.sweep` isn't wired as an automatic job** — needs a new `kernel:scheduler` permission grant, its own ADR.
4. **`project.pause`/`.resume`/`.archive`/`.abandon`** — re-confirmed not ripe this session, deliberately: no lived instance yet of Kang wanting to shelve or kill a project and hitting a wall.
5. **Palette "New goal…"** — checked this session and found **already built** (a stale item carried forward incorrectly in an earlier draft of this session's own next-step list; corrected in conversation, not silently). No action needed here.
6. **No real D016 packaged installer** — re-confirmed not ripe: not enough surface area to package yet, and no real migration has ever been staged/rehearsed to prove the "migrate on a copy, verify, swap" story works. Start-at-login (ADR-017) remains a hand-registered Startup-folder shortcut, not part of any installer.
7. ~~**ADR-008's core-side single-instance lock**~~ — **closed this session.** Was: "the shell half is real; the Core half is only narrowly worked around." Now: both halves real.
8. **Learn/Know/Chat** — Learn confirmed not ripe (prior session); this session additionally ruled Know/Chat *scoping itself* premature, not just the building — a scoping document with no Phase 2 memory architecture underneath it would mostly be guessing. Revisit Know once Phase 2's write-gate + Context Assembler exist in real, working form; Chat once Phase 3's agent roster exists.

---

## 5. Working discipline this session actually followed (keep doing this)

- **A real design conversation before building anything** — read the actual constitution, ADR-008/017's own text, the schema, and the RESERVED registry directly rather than reasoning from a prior summary (the prior summary was explicitly rejected as a starting point: "I need to read the actual documents before ruling on anything, not reason from the summary you gave me"). Four verdicts came back, three "not ripe" and one "here's the real next increment" — not a rubber stamp on any of them.
- **Verified a claimed gap before repeating it** — "New goal…" was carried forward on a next-steps list as missing; a direct grep before touching anything found it already fully built and tested from an earlier session. Corrected in conversation rather than silently building a duplicate or leaving the wrong claim standing.
- **Live-verified the transitions UI in a real browser, not just Vitest** — booted a throwaway Core, seeded real project/goal/milestone rows via curl, ran the Vite dev server against that Core's real session (the documented `VITE_DEV_SESSION_*` dev-fallback path), and clicked every one of the six transition buttons for real, checking the resulting `kang.db` rows afterward.
- **Live-verified the startup lock with two genuine OS processes**, not a mocked scenario — `tests/suites/replay/test_single_instance.py` spawns two real `python -m kang.kernel.runtime.composition` subprocesses against the same real temp `%KANG_HOME%` and checks the second's actual exit code and stderr, and the first's actual untouched session file.
- **A test's own wrong assumption got caught and fixed by running it for real**, not reasoned around in the abstract — the "read the lock file while held" test failed with a real `PermissionError`, which turned out to be a genuine Windows behavior worth learning and documenting, not a bug in the lock itself (11 other assertions already proved exclusivity cleanly).
- **Restarted the real Core specifically because new backend code landed** — did not declare the session done while the resident Core was still running yesterday's code holding no lock at all; stopped it, relaunched via the real launcher, confirmed 36 operations and a held lock file before calling it verified.
- **Commit per coherent slice, real messages via `git commit -F <file>`, never inline `-m`** — held all session.
- **Never pushed without explicit instruction** — held all session; pushed only when asked, after a fresh full test run each time.
- **ADR-008 amended in place, never rewritten** — matches ADR-001's own established precedent, the same discipline the 2026-08-09 handoff used for its own correction to ADR-012.

---

## 6. Next step

Pick based on priority — none of these is committed to:

1. **The continuous scheduler tick loop** — needs a design decision first (the supervised-task primitive), not just code. Worth a real conversation, same shape as this session's own design pass, before starting.
2. **`deadline.sweep` as an automatic job** — needs its own small ADR (the new `kernel:scheduler` scope grant) before any code.
3. **First Appendix D consequential operation** (`calendar.write` is the named likely candidate, per both this session's and the prior session's own investigation) — the real trigger for `held_action.approve → executed`, per this session's sharpened verdict. Its own ADR would need a real idempotency contract for the target adapter before declaring `commit_mode="redrive"` (ADR-001's amendment gate).
4. **CSS/visual polish on the new transition buttons** — functional, minimally styled (plain bordered text buttons). Not urgent.
5. Something else entirely — Know/Chat both still blocked on Phase 2/Phase 3 architecture that doesn't exist yet, per §4 item 8.

Before doing real work: run `git status`, `git log --oneline -15`, the full test suite, **and check whether the real Core needs a restart** (compare its live `registry.get` operation count and, now, whether `%KANG_HOME%/core.lock` is actually held by the process you think is running it) — don't assume this handoff is still accurate by the time you read it, and don't assume "it's running" means "it has today's code." Same discipline it was written with.
