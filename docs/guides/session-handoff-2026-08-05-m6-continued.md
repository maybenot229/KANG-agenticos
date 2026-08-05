# Session handoff — 2026-08-05 (M6 continued)

Everything below was verified against the actual repo state at handoff time (git log, a fresh full test run, a fresh lint run, live Core boots), not recalled from memory or from the prior handoff. This supersedes `session-handoff-2026-08-05.md` for current state — that file's own content (the shell incident, the Tauri ACL question) is fully resolved and archived there; this file picks up from where M6 stood after those were closed.

---

## 1. State (verified just now)

```
git status --porcelain   → (empty — clean working tree)
git rev-list --count origin/main..HEAD   → 17
python -m pytest tests/unit tests/suites tests/integration -q   → 574 passed
ruff format --check src tests tools cli   → 233 files already formatted
ruff check src tests tools cli            → All checks passed!
lint-imports --config tools/importlinter.toml → Contracts: 8 kept, 0 broken
python tools/lint_sizes.py src            → 0 hard violation(s), 25 soft warning(s)
python tools/lint_banned_patterns.py src  → 0 violation(s)
python tools/lint_tree_hygiene.py .       → 0 violation(s)
python tools/build_root_docs.py --check  → CLAUDE.md is current.
cd ui && npm run typecheck && npm run build → both clean
```

17 commits ahead of `origin/main`. **Nothing pushed** — `git push` needs separate, explicit instruction, same rule as always.

### Commits landed this session (newest first)

```
58311ee feat(M6): System-domain Activity + Health views (09_UI §12)
05ebf4c feat(M6): command palette — Decision UI-002's "one palette, three registers"
a5a75cf feat(M6): confirm dialog — 09_UI §7's "most safety-critical UI"
f289d74 feat(M6): permission screen — 09_UI §7's "what can KANG touch?"
a93379f feat: wire held_action.approve/.cancel — the confirmed-open ADR-001/002 gap
3f4d7f4 feat(M6): seven domain shells — real navigation, real data where real
5929b7e feat(M6): three remaining dashboard zones — real data or honest gaps
fea32ae feat(M6): NFR-011 overlay — global hotkey -> standalone window -> gone
42c1129 docs: root-cause shell incident; resolve Tauri capabilities ACL question
```

(Below `42c1129`, `730eebc` and earlier are the prior session's vertical-slice work — already covered by the earlier handoff, not repeated here.)

---

## 2. What's actually built now (M6 UI surface)

Everything 09_UI names for M6 is built and **live-verified** (real Core, real HTTP, real browser at the shell's actual 800×600 window size — not just typecheck/build) at least once:

- **Dashboard, all 4 zones** (09_UI §4): Zone 1 (Today's Quests), Zone 2 (Attention — real deadline horizon + real approval queue), Zone 3/4 (What Changed / Opportunities — honest empty states, no backend exists for either).
- **All 7 domain shells** (Plan/Projects/Competitions/Learn/Know/System/Chat) — real client-side routing (previously the buttons did nothing). Plan and System are real; Projects/Competitions/Learn/Know/Chat are honest empty screens (their domains are empty stubs in `src/kang/domain/`, verified by reading the actual directories, not assumed).
- **NFR-011 overlay** — the real global-hotkey (Ctrl+Shift+Space) → standalone Tauri window → gone path, replacing the placeholder left-rail button. Verified with a genuine OS-level `keybd_event` injection while another app had focus.
- **Permission screen** (09_UI §7) — `PermissionsPanel`, real `permissions.toml` grants with plain-language consequences.
- **Confirm dialog** (09_UI §7) — `ConfirmDialog`, renders real `held_action` rows, Deny holds real keyboard focus (verified via `document.activeElement`), Escape denies in one keystroke.
- **Command palette** (UI-002) — `Palette`, Ctrl+K, real Navigate (8 locations) + one real Act command ("New task…" → opens QuickCapture) + honest Find note (no memory search exists).
- **System domain Activity + Health** (09_UI §12) — real audit stream, real job statuses + kill-switch state.

### New backend operations added this session (all pure exposure of already-existing store/engine methods — no new domain logic invented, each verified this way before being trusted)

| Operation | Exposes | Scope |
|---|---|---|
| `deadline.list` | `DeadlineStore.active()` | `deadlines.read` |
| `held_action.approve`/`.cancel` | `HeldActionStore.approve/cancel` | first_party_only, `commit_mode=transactional` |
| `held_action.list` | `HeldActionStore.pending()` | `held_actions.read` |
| `permission.list` | `PermissionEngine.snapshot()` (new method) | None |
| `audit.list` | `AuditService.records()/.months()` (new thin pass-throughs) | None |
| `system.health` | `JobStore.list_jobs()/.consecutive_failures()`, `KillSwitch.is_engaged()` | None |

Registry is now at **19 operations**, contract version 1.

---

## 3. Architectural changes worth knowing about

**`composition.py`'s scheduler wiring was restructured.** `job_store`/`kill_switch` used to be constructed *inside* `_wire_scheduler`, which only runs its body when `kang.toml` loads successfully (07 F8's fail-closed shape) — meaning they didn't exist at all if automation wasn't configured. Moved construction into a new `_build_stores()` helper, called unconditionally in `build_core`, so the Health view works regardless of whether `kang.toml` is present. `_wire_scheduler` now receives both via `_SchedulerWiring` instead of building its own. **Verified both configurations live**: no `kang.toml` → empty jobs list, `automation_engaged: false`, boots clean; real `kang.toml` → the real `morning_plan` job shows up with its actual schedule.

This also required extracting `_build_stores()`/`_Stores` purely to keep `build_core` under the size lint's 80-line hard limit — it hit 90 lines with the construction inlined, and the lint suite caught this for real mid-session (not a hypothetical), fixed before moving on.

**`AuditService` gained two methods** (`months()`, `records(month)`) rather than handing the raw `AuditLog` port to `operations.py` — the class's own docstring says "nothing else holds the AuditLog port," so thin pass-throughs preserve that boundary (same pattern as `PermissionEngine.snapshot()`).

**`EmptyState.tsx`** (in `ui/src/common/`) is the shared "honest gap" component — used by dashboard Zones 3/4 and by all five empty domain screens. If you're tempted to write a new "not built yet" message component, this one already exists.

**`useQuickCapture.ts`** is the shared task-creation submit logic — used by both the inline QuickCapture panel and the standalone overlay window, and also what the palette's "New task…" command opens rather than reimplementing.

---

## 4. Known, named, real gaps — not forgotten, deliberately not built

Every one of these was hit, considered, and explicitly scoped out with a stated reason — re-read the relevant commit message before assuming any of them is trivial:

1. **`InvocationStore` has no list method at all** (only `by_correlation`, a point lookup) — "Invocations" (09_UI §12) needs a new port method + SQL, genuinely new domain-layer work, not just exposure. Bigger than everything else in this table.
2. **Ledger (model spend)** — nothing to expose; no model calls exist yet (M4/M5 are zero-model by construction). Not buildable until M7.
3. **Backup age / restore-verification / index parity / integrity-incident counter** (09_UI §12, Health) — no port or store tracks any of these yet.
4. **`deadline.create`/`plan.generate` have no UI form** — real operations, but nothing in the UI drives them yet beyond what already exists (Zone 1 auto-generates the plan; deadlines can only be created via direct API calls in this session's live tests, never through a form).
5. **Palette's Act register is exactly one command** ("New task…") — deliberately not stubbing in deadline/plan commands without the forms above.
6. **No automated UI-interaction tests anywhere.** Every interactive feature this session (quick capture's DOM layer, the confirm dialog's keyboard behavior, the palette's Ctrl+K/Escape/Enter) was verified **live**, by real browser interaction or real DOM event dispatch — never by an automated test harness. This has been flagged every single time it came up; don't let any future "tested" claim generalize past what was actually run.
7. **The Browser pane's synthetic key-press action doesn't reliably reach focused inputs** in this environment (hit twice this session — palette's Enter key, confirmed via direct `KeyboardEvent` dispatch as the reliable workaround). If a live UI test seems to silently fail on a keypress, dispatch a real `KeyboardEvent` via `javascript_tool` to isolate whether it's the pane or the code before concluding either way.

---

## 5. Working discipline this session actually followed (keep doing this)

- **Before building any UI screen touching a domain, checked what backend reality actually was** — grepped `src/kang/domain/<name>/` for non-`__init__.py` files, checked the registry for operations, before writing a line of frontend code. Every domain screen's docstring cites the exact finding.
- **Every "expose an existing store method" addition followed the same shape**: confirm the underlying method already exists and is already used somewhere internally, add a thin handler + schema + registry entry, no new domain logic. When that wasn't true (Invocations), said so and stopped rather than inventing the missing piece.
- **Live verification, every single feature, no exceptions**: booted a real throwaway Core (`python -m kang.kernel.runtime.composition <dir> 127.0.0.1 0`), copied `config/defaults/permissions.toml` in first (a bare `KANG_HOME` fails closed to Kang-only grants and silently blocks every event-publishing write — cost real time once this session, now written down so it doesn't again), often also `config/defaults/kang.toml` when scheduler behavior mattered. Seeded real data via direct SQL or real HTTP calls, drove the actual UI, checked real DB state and audit trail afterward — never trusted a screenshot alone.
- **Caught and fixed real bugs this way that reasoning alone wouldn't have caught**: two separate CSS overflow bugs at the real 800×600 window size (grid `min-width: auto` default; a table wider than the window), a missing `idempotency_key` on the confirm dialog's `held_action.cancel`/`.approve` calls (both are commands, both need one — the dialog looked right, failed on first real click), the `build_core` size-lint violation.
- **Commit per coherent slice, real messages via `-F <file>`, never inline `-m`** (backticks in a commit message triggered real shell command substitution earlier this same day — root-caused, see the prior handoff — the file-based-message rule stays permanent regardless).
- **Never push without separate explicit instruction.** Still true; nothing pushed this session either.
- **Clean up every throwaway test directory and process** after each live verification — `taskkill`/`Stop-Process` the Core and Vite processes, `rm -rf`/`Remove-Item` the temp `KANG_HOME` dir. One session-long lesson: on Windows, a lingering file handle can make `rm -rf` fail with "Device or resource busy" even after the obvious process is killed — check `Get-Process python`/`Get-Process node` via PowerShell if `rm` won't cooperate, not just `ps aux` (which doesn't reliably see native Windows processes from Git Bash).

---

## 6. Next step

Pick based on priority — none of these is committed to:

1. **`InvocationStore.list_recent()` (or similar) + Invocations view** — the biggest remaining 09_UI §12 gap, needs real port/adapter design work (ordering, limits, whether to include `manifest`), not just exposure.
2. **Deadline creation form** — would unlock a real "New deadline…" palette Act command and a proper deadline-management UI (today, deadlines can only be created via direct API calls in tests).
3. **Automated UI-interaction test harness** — every interactive feature has been live-verified but never covered by an automated test. If this keeps mattering, it may be worth a deliberate decision (and possibly a new dependency/ADR — Vitest + Testing Library or Playwright are the obvious candidates, neither currently in `ui/package.json`) rather than continuing to defer it session after session.
4. **`held_action.approve`'s "drive to `executed`"** — still open from the earlier session: the row has no stored params to replay the held operation with. Real schema-delta work, flagged in ADR-001's own Consequences section as "owed."
5. Something else entirely — Chat/Learn/Know/Projects/Competitions all still have zero backend; each would need real domain-layer work before any UI beyond the current honest-empty screens makes sense.

Before doing real work: run `git status`, `git log --oneline -10`, and the full test suite yourself — don't assume this handoff is still accurate by the time you read it. Same discipline it was written with.
