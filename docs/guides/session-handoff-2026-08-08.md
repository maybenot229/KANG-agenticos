# Session handoff — 2026-08-08

Everything below was verified against the actual repo state at handoff time (git log, a fresh full test run, a fresh lint run, fresh UI typecheck/build/test) — not recalled from memory or from the prior handoff. This supersedes `session-handoff-2026-08-05-m6-continued.md`, which this session picked up from at commit `786ee49`.

---

## 1. State (verified just now)

```
git status --porcelain            → (empty — clean working tree)
git rev-list --count origin/main..HEAD → 0 (everything pushed)
python -m pytest tests/unit tests/suites tests/integration -q → 667 passed
ruff format --check src tests tools cli   → 270 files already formatted
ruff check src tests tools cli            → All checks passed!
lint-imports --config tools/importlinter.toml → Contracts: 8 kept, 0 broken
python tools/lint_sizes.py src            → 0 hard violation(s), 31 soft warning(s)
python tools/lint_banned_patterns.py src  → 0 violation(s)
python tools/lint_tree_hygiene.py .       → 0 violation(s)
python tools/build_root_docs.py --check   → CLAUDE.md is current.
cd ui && npm run typecheck && npm run build && npm run test → all clean, 41/41 UI tests
```

`main` is at `0127750`, fully pushed — **nothing local, nothing unpushed.**

### Commits landed this session (chronological)

```
b1204f4 feat(M6): invocation.list + System-domain Invocations view (09_UI §12)
3cc6992 feat(M6): deadline creation form — Zone 2 + palette "New deadline…"
db20e68 feat(M6): ADR-012 + automated UI-interaction test harness
aa671b5 feat(M5): Projects domain — tracking only (ADR-013)
29c6b87 docs: accept ADR-012 and ADR-013
fe44ca1 feat(M5): Competitions domain — tracking only (ADR-014)
b7e3f79 docs: accept ADR-014
bc26871 fix(shell): tray icon never appeared — bundle.icon was empty
a611337 ci: run the UI test suite; correct ADR-012's "no CI exists" claim
e077541 test(ui): broaden UI-interaction coverage past ADR-012's stated floor
6ce6a88 feat(M5): Milestones under Projects — tracking only (ADR-015)
0127750 docs: accept ADR-015
```

(`bc26871`, the tray-icon fix, was actually authored in a separate spawned session working in its own worktree — this session reviewed the diff, verified it live with real desktop control, and merged it in. Everything else was built directly in this session.)

Registry is now at **26 operations**, contract version 1. ADR count: **15** (001–015), all accepted except two pre-existing, unrelated to this session's work: ADR-008 (single-instance enforcement) and ADR-011 (TS client generator) are still `proposed` — not touched, not blocking anything, just noting they exist if a future session wonders.

---

## 2. What's actually built now

Everything below is **live-verified** (real Core, real HTTP, real browser at the shell's actual 800×600 window size, or — for the desktop shell itself — the real native Tauri window) at least once this session:

- **`invocation.list` + Invocations view** (09_UI §12) — `InvocationStore` gained its first list method (`recent(limit)`, new port surface, migration 0010's index). The System screen's Invocations panel is the first real renderer of `explain.invocation` anywhere in the UI — each row expands to the actual reconstructed chain.
- **Deadline creation form** — Zone 2's "+ New deadline" and the palette's "New deadline…" both open the same `DeadlineForm`. `kind` only offers self-standing values (`custom`/`school`) since Competitions/Projects didn't exist yet when this landed.
- **ADR-012 + Vitest/Testing Library harness** — the project's first UI test tooling. Initially scoped to 3 components (QuickCapture, ConfirmDialog, Palette); broadened later this session to 7 (`InvocationsPanel`, `DeadlineForm`, `ProjectForm`, `CompetitionForm` added) — 41 tests total.
- **Projects domain (ADR-013)** — `project.create`/`.list`, tracking only. First real write path for `project`, which meant registering `project.created` (EB-004's five-step write order requires it) and discovering `0006_domain_entities.sql` never wired a change-capture trigger for `project`/`competition`/`milestone`/`goal` (only `task`/`deadline` had one at the time). Migration 0011 closed that gap for `project`.
- **Competitions domain (ADR-014)** — `competition.create`/`.list`, identical shape to Projects. Closed the other half of ADR-004's explicitly-deferred item. Corrected `CompetitionsScreen.tsx`'s own stale docstring along the way (it over-claimed tracking was Phase-2 work; only discovery/evaluation actually is).
- **Milestones under Projects (ADR-015)** — `milestone.create`/`.list`, third instance of the same pattern. Two things genuinely new: `milestone.project_id` is `NOT NULL` (no self-standing case like deadline has), which forced adding a `seed_sql` field to the payload-sufficiency suite's `Fixture` dataclass so an FK-constrained recovery-grade type can seed its parent row; and `project → milestone` is this session's first CASCADE relationship, proven (not assumed) that SQLite fires the child's own `AFTER DELETE` trigger when a CASCADE removes it. **First depth-2 UI view any domain has built** — `ProjectsScreen` rows are now clickable into `ProjectDetail`, showing that project's milestones.
- **Tray icon fix** — the real desktop shell's system tray icon never rendered (`tauri.conf.json`'s `bundle.icon` was `[]`; `default_window_icon()` always returned `None`; `main.rs`'s tray-building code silently no-opped). Fixed, and this session personally verified it by clicking the actual tray icon and watching "Show KANG" open the real window with real persisted data.
- **CI now covers the UI suite** — `ci.yml` had zero Node/UI jobs before this session; added a parallel `ui` job (typecheck, build, `npm run test`).
- **`KANG_HOME` is real and persistent now** — `C:\Users\meime\kang-home`, set as a permanent User environment variable. Every throwaway `KANG_HOME` used for live-verification this session was a *separate*, scratchpad-scoped directory, deliberately never the real one — Kang's actual data (a couple of real tasks, one real project, some real milestones from the live walkthrough) lives in the real one untouched by test noise.

### Held_action.approve → executed: investigated, deliberately NOT built

This was on the candidate list going into this session. Read ADR-001 in full (including its commit-mode amendment — the design is already fully decided, `transactional` vs `redrive`, registration-time idempotency gate, all of it). Then verified directly: **nothing in `src/` ever calls `held_action_store.create()`**, and no registered operation declares a `commit_mode`. The approval queue is permanently empty by construction — none of 05_AGENTS Appendix D's closed-list consequential actions (`calendar.write`, `vault.delete`, `memory.delete`, etc.) exist yet. Building redrive/executed machinery now would mean inventing a fake consequential operation just to exercise it — exactly the speculative-structure pattern this project has rejected everywhere else (`project.updated`, `competition.updated`, `competition.*` events, all deferred for lack of a real consumer). **Not ripe. Don't build it until a real consequential operation exists to drive.**

---

## 3. Architectural notes worth knowing

- **`src/kang/api/operations.py` is now a package**, not a flat file. It crossed the size lint's 800-line hard limit the moment `project.create`/`.list` landed. Split into `operations/{registry,task,deadline,plan,notification,held_action,explain,system,project,competition,milestone}_ops.py` + `__init__.py` re-exporting everything — `from kang.api.operations import make_X_handler` still works unchanged everywhere. If you're about to add another domain's operations, put them in their own `_ops.py` file from the start; don't reopen this question.
- **The "register a `.created` event + add a change-capture trigger" pattern has now happened three times** (`project`, `competition`, `milestone`), each with its own ADR (013, 014, 015). ADR-015's own Consequences section flags this explicitly: *"if a fourth M5-scoped entity needs the same treatment, that is the point at which... it might warrant a single standing ADR covering the shape generically."* `goal` is the obvious fourth candidate (same 0006 migration, same missing trigger, same missing event) — if you're building it, read that flag first and consider whether a generic ADR beats a fourth near-identical one.
- **Payload-sufficiency `Fixture` dataclass gained a `seed_sql` field** (`tests/suites/replay/test_payload_sufficiency.py`) — for FK-constrained recovery-grade types whose row can't exist in a truly empty store. Reusable now, not milestone-specific.
- **`composition.py`'s bus/audit/engine/notifier wiring is in `_build_bus_wiring`**, extracted from `build_core` (mirrors the pre-existing `_build_stores` extraction) purely to stay under the size lint's 80-line function limit. `build_core` is at 66 lines now with 6 stores wired through it (`task`, `deadline`, `invocations`, `held_action`, `project`, `competition`, `milestone` — that's actually 7); if an 8th store gets added, it may cross 80 again and need another look.
- **The real desktop app's known limitation**: `ui/shell/tauri.conf.json`'s main window is `visible: false` by design (Decision 016: "core lives in the tray, UI opens on demand"). The *only* way to reach it is the tray icon → "Show KANG" — confirmed working now (see the tray fix above). There is still no in-app way to reopen it if the tray icon is somehow missed/dismissed; that's the architecture's own stated shape, not a gap.

---

## 4. Known, named, real gaps — not forgotten, deliberately not built

1. **`held_action.approve` → `executed`** — see §2 above. Genuinely blocked on a real consequential operation existing. Don't build ahead of it.
2. **`goal`** — real schema (0006), zero domain layer, same shape as `project`/`competition`/`milestone` before this session. Natural next entity if you want a fourth instance of the pattern (or the moment to write the generic ADR ADR-015 flagged).
3. **Palette has no "New project…"/"New competition…"/"New milestone…" commands.** Only "New task…" and "New deadline…" exist. Adding more would need lifting `formOpen` state through `App.tsx`'s generic `DOMAIN_SCREENS` render map, which doesn't currently pass props to per-domain screens — a real, deliberate scope boundary from the Projects-domain session, never revisited since.
4. **`ProjectsScreen`'s click-through to `ProjectDetail` has no dedicated UI test.** Every other interactive surface added this session (`ProjectForm`, `CompetitionForm`, `DeadlineForm`, `InvocationsPanel`) got Vitest coverage; the click-into-detail flow didn't, purely because it was the very last thing built this session. Real gap, not silently skipped — named here so it isn't lost.
5. **No milestone status transitions** (`reach`/`miss`/`drop`) — `milestone.updated` isn't registered, deliberately, same non-speculation discipline as `project.updated`/`competition.updated`.
6. **`03_ROADMAP.md`'s M4 objective line and the M5 migration header disagree slightly** on whether "projects/deadlines/competitions (tracking only)" is M4 or M5 scope — never resolved, just navigated around by reading both and building against the schema that actually existed. Not urgent, but a real, small doc-tension someone could clean up.
7. **Learn/Know/Chat** — Learn's own schema (`quiz_result`/`repetition_item`) isn't even migrated yet (unlike `goal`/`milestone`, which are real schema with no domain layer — Learn doesn't have that far). Know (memory) and Chat are genuinely Phase 2/M7. Don't start here without a much bigger scoping conversation first.

---

## 5. Working discipline this session actually followed (keep doing this)

- **Before touching a candidate task, verified it was actually ripe** — the held_action investigation is the clearest example: read the full ADR, then grep'd the actual codebase for `held_action_store.create()` callers before writing a line of redrive logic, found zero, and said so instead of inventing a fake consequential operation to justify building it.
- **Every ADR reviewed before being trusted, even ones written this same session** — spot-checked each claim (event registered? recovery applier wired? migration exists? tests pass?) against real code and a fresh full test run before flipping `proposed` → `accepted`. Never rubber-stamped.
- **Live-verified every feature against a real Core, every time, no exceptions** — booted throwaway `KANG_HOME`s (never the real persistent one) for every backend/UI check, copied `config/defaults/permissions.toml` in first (still the #1 trap — a bare `KANG_HOME` fails closed and silently blocks every write), drove real browser interactions via the Browser pane, confirmed real `kang.db` state and real audit-trail rows afterward.
- **The one time this went beyond the Browser pane** — verifying the tray icon fix needed the actual native Tauri window, which the Browser pane can't reach. Used `mcp__computer-use__*` tools instead: requested access, screenshotted the real desktop, clicked the actual tray icon (took several tries — Windows' notification-area flyout doesn't reliably accept synthetic clicks; pinning the icon to the always-visible tray area first, then a precise zoom-then-click, is what worked), watched the real "Show KANG" menu item open the real window with real persisted data.
- **Commit per coherent slice, real messages via `git commit -F <file>`, never inline `-m`** — held all session, no exceptions, no backtick incidents.
- **Never pushed without separate explicit instruction** — held all session; pushed only when directly asked, several distinct times.
- **Cleaned up every throwaway test directory and process afterward** — `taskkill`/`Stop-Process` (via PowerShell, more reliable than Bash's `ps`/`kill` for native Windows processes) after every live-verification pass, `rm -rf` every scratchpad `KANG_HOME`. Caught and fixed one real incident: an early boot attempt landed `kang.db`/`session.json`/`events/`/`audit/` at the repo root by mistake (wrong `KANG_HOME` resolution) — cleaned up, and closed the actual gap (`session.json` had no `.gitignore` pattern, unlike its `*.db` siblings, which is why it survived as untracked instead of silently ignored).
- **Corrected factual errors in already-accepted ADRs by appending, never rewriting** — ADR-012 claimed no CI pipeline existed; that was false and easy to verify wrong. Followed ADR-001's own established precedent (its "Amendment" section) rather than editing the original text away.

---

## 6. Next step

Pick based on priority — none of these is committed to:

1. **`goal`** — the natural fourth instance of the `project`/`competition`/`milestone` pattern, or the trigger point for writing the generic "register a sub-entity's `.created` event" ADR ADR-015 already flagged instead of a fourth near-identical one. Real schema, zero domain layer, same shape as three things already built this session.
2. **UI test for `ProjectsScreen` → `ProjectDetail` click-through** — the one named gap in an otherwise now-well-covered UI surface (7 components, 41 tests).
3. **Palette "New project…"/"New competition…"/"New milestone…"** — needs the `App.tsx` per-domain-screen-props question resolved first (see §4 item 3); not a quick add.
4. **`held_action.approve` → `executed`** — still blocked on a real consequential operation existing. Don't build ahead of it; revisit once one does (most likely candidate: whichever of Appendix D's list gets built first — `calendar.write` is probably the natural first mover given the Planner already touches calendar reads).
5. Something else entirely — Learn/Know/Chat all still need real scoping conversations before any code, per §4 item 7.

Before doing real work: run `git status`, `git log --oneline -15`, and the full test suite yourself — don't assume this handoff is still accurate by the time you read it. Same discipline it was written with.
