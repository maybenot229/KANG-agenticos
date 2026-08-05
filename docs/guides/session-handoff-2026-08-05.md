# Session handoff — 2026-08-05

Everything below was verified against the actual repo/environment at handoff time, not recalled from the prior session's report. Commands and their real output are included so the next session doesn't have to re-trust anything.

---

## 1. State (verified just now)

### `git status`

```
On branch main
Your branch is ahead of 'origin/main' by 8 commits.
  (use "git push" to publish your local commits)

nothing to commit, working tree clean
```

`git status --porcelain` returned nothing — zero staged, unstaged, or untracked files. Nothing pending from the prior session; everything it did is either committed or was cleaned up (temp verification dirs, throwaway Core/Vite processes).

### `git log --oneline -15`

```
730eebc feat(M6): vertical slice - API client, Zone 1, quick capture, real end-to-end
b718b81 feat(ADR-011): implement the registry -> TypeScript client generator
c7b3164 feat(M6): scaffold ui/src/ on Vite + React + TypeScript
9cbc0f1 docs: file ADR-011 (proposed) — TS client generator picks json-schema-to-typescript
c12eca0 feat(ADR-010): implement Ruling 4 — dispatch-time schema validation
370d6bf docs: ADR-004/005 INDEX status sync; held_action gap audit; ADR-010 session reports
32e81e5 feat(ADR-010): implement Rulings 1-3 across all 7 real-handler operations
ac2fa73 deps: add pydantic (Kang-approved) for ADR-009/010 schema authority
b662633 fix: add tzdata dependency for Windows zoneinfo; amend ADR-006 (CI: ZoneInfoNotFoundError on windows-latest)
9a2edca lint: fix ruff check (unused imports, import ordering) - CI commit-tier fix
508d858 style: apply ruff formatting (CI commit-tier fix)
b1741ee ADR-010: accept all four rulings (Kang review 2026-07-31); sync INDEX status
86d4504 ADR-010 (proposed): Pydantic implementation layout, attachment, null-schema, error mapping
740cb22 17_PROJECT_STRUCTURE §4.2: correct stale FastAPI reference, cite ADR-009
e6a83e8 03_ROADMAP §8: scope Rulings A/B by ADR-009, retrigger Ruling C
```

8 commits ahead of `origin/main` (`e6a83e8` is the last pushed commit; everything above `740cb22` is unpushed). **Nothing has been pushed.** `git push` requires separate, explicit instruction — not implied by anything in this handoff.

### Full verification suite (actual counts)

```
python -m pytest tests/unit tests/suites tests/integration -q
538 passed in 55.05s
```

```
ruff format --check src tests tools cli   → 226 files already formatted
ruff check src tests tools cli            → All checks passed!
lint-imports --config tools/importlinter.toml → Contracts: 8 kept, 0 broken
python tools/lint_sizes.py src            → 0 hard violation(s), 22 soft warning(s)
python tools/lint_banned_patterns.py src  → 0 violation(s)
python tools/lint_tree_hygiene.py .       → 0 violation(s)
python tools/build_root_docs.py --check   → CLAUDE.md is current.
```

All green, all just re-run, not carried over from the prior report.

---

## 2. The shell incident — ROOT-CAUSED (2026-08-05 follow-up)

**Resolved.** Extracted the exact `git commit -m "..."` command from the raw
session transcript (`C:\Users\meime\.claude\projects\C--KANG---Agentic-OS\422f2dad-4f82-4e91-988e-7b5fcc8a48a5.jsonl`,
line 2279 — the actual tool call, not a recollection). The commit message
contained exactly two backtick-quoted spans (4 backticks total, confirmed by
`grep -o` on the raw line):

- `` `kang_cli.py task get` `` — inside the prose describing how quick capture
  was verified
- `` `cargo tauri dev` `` — inside the prose describing what was *not* yet
  tested

The `-m` argument was double-quoted, and bash performs command substitution
on backtick spans even inside double quotes. Both were substituted as real
commands: `kang_cli.py` isn't on PATH → `command not found` (already
confirmed); `cargo tauri` **is** a real installed subcommand → it genuinely
ran, producing the observed BeforeDevCommand/DevCommand pipeline and crate
compilation. `cargo tauri dev` starts a long-running dev server that never
exits on its own, so the substitution blocked until the Bash tool's 2-minute
timeout killed the process tree — explaining both the timeout and why
nothing was left running. No hook, alias, or external mechanism was
involved; the commit message's own prose was the trigger. The original
(now superseded) investigation below is kept for the record.

### Original investigation (superseded — kept for record)

**Do not treat this as closed.** The prior session's `git commit -m "..."` (a message containing unescaped backticks) produced output showing a real Tauri dev-build pipeline running (`Running BeforeDevCommand`, `Running DevCommand`, real `cargo` compilation of ~369 crates), then timed out at 2 minutes. The commit did not land; no process was left running afterward (both confirmed at the time and re-confirmed just now).

**What I checked, just now, and what each check found:**

| Check | Result |
|---|---|
| `.git/hooks/` (real hooks, not `.sample` files) | **Empty.** No pre-commit, post-commit, or any other hook exists. |
| `git config --get core.hooksPath` (local and global) | **Empty.** Default hooks path, which is confirmed empty above. |
| husky / lint-staged / simple-git-hooks config | **None found** — grepped `ui/package.json` and the repo for these; no matches. |
| Shell aliases (`alias`) | **None.** |
| Shell functions matching cargo/tauri/dev (`declare -F`) | **None.** |
| `PROMPT_COMMAND`, active `trap` handlers | **None set.** |
| `.bashrc`/`.bash_profile`/`.profile` for cargo/tauri references | **None found.** |
| Is `kang_cli.py` on PATH? | **No** (`which` returns not-found) — this **fully explains** the `"kang_cli.py: command not found"` line in the original output: the commit message contained the literal text `` `kang_cli.py task get` `` (backtick-quoted, describing how a task was verified), and bash performs command substitution on backtick-quoted text inside a double-quoted `-m` argument. That specific error line has a confirmed, mechanical explanation. |
| Is `cargo tauri` a real, installed subcommand? | **Yes** — `cargo tauri --version` → `tauri-cli 2.11.4`, confirmed installed and functional. This means **if** the commit message's text contained a backtick-quoted fragment equal to (or resolving to) `cargo tauri dev`, bash would have genuinely executed it, and the observed output (BeforeDevCommand/DevCommand orchestration, real crate compilation) is exactly what that would produce. |

**What is NOT resolved:** I do not have access to the exact, verbatim text of the original failed `git commit -m "..."` tool call from this vantage point — only my own narrated description of composing it. I can state with high confidence that backtick-triggered command substitution is the general mechanism (proven by the `kang_cli.py` line), and that `cargo tauri dev` being a real, installed command explains how that specific pipeline could have been triggered this way — but I cannot point to the exact substring in the original message that did it, and I have not ruled out with certainty that some other mechanism contributed.

**Recommendation, not yet done:** if a full root cause is required before trusting unattended commits again, the original tool-call transcript (outside what I can re-query from here) would need to be inspected directly for the exact backtick-quoted spans in that specific `-m` string. Until then, the safe operating rule (already adopted for the rest of that session) is: **never pass a commit message via inline `-m` with backticks in it — always write the message to a file and use `git commit -F <file>`.** That workaround avoids recurrence; it does not constitute a root cause.

---

## 3. Open items — verified by reading the actual files just now, not cited from memory

| Item | Status | Evidence |
|---|---|---|
| `held_action.approve`/`.cancel` handlers | **confirmed-resolved (2026-08-05, follow-up session)** | `make_held_action_approve_handler`/`make_held_action_cancel_handler` (`src/kang/api/operations.py`) drive the already-built `HeldActionStore` (port + fake + sqlite adapter existed since M3; only the API-layer wiring was missing) through `pending -> approved \| cancelled`. Wired into `composition.py`'s handler table. Verified live against a real Core over real HTTP, not just unit tests: seeded a held action directly in `kang.db` (nothing live creates one yet — see below), approved it via `POST /op`, confirmed the committed status in the DB and the audit trail (`held_action.approve.dispatched`/`.ok`), confirmed a second approve attempt correctly fails `not_found`. **Not built:** driving an approved action to `executed` (ADR-001 Decision #3) — the `held_action` row has no stored params to replay the original operation with (schema carries `operation`/`action` only, never params; ADR-001's own Consequences section calls this schema delta "owed... applied by the follow-through PR", not silently invented here), and moot in practice since no operation currently registered is on 05_AGENTS Appendix D's closed list, so nothing live produces a held action to drive. Genuinely open, named, not hidden. |
| `commit_mode` missing on `held_action.*` registry entries | **confirmed-resolved (2026-08-05)** | Both entries now declare `commit_mode="transactional"` — justified as describing these operations' own direct effect (a `held_action.status` flip, always one `kang.db` write, ADR-001 Amendment's default case), distinct from the commit_mode of whatever operation the held action names (separate registry metadata, only relevant once effect-driving is built). |
| ADR-010 Ruling 4 (dispatch-time schema validation) | **confirmed-resolved** | `src/kang/api/dispatch.py` has `_validate_schema`, imports `pydantic.ValidationError`, calls `schema.model_validate(request.params)`, and sanitizes via `_sanitized_field_errors`. Backed by the passing test suite (538/538) which includes `tests/unit/kang/api/test_dispatch.py`'s Ruling-4-specific cases and `tests/suites/contract/test_schema_validation_conformance.py`. |
| Tauri capabilities ACL for `get_session` | **confirmed-resolved (2026-08-05, live launch)** | Ran a real `cargo tauri dev` against a throwaway Core, with the main window temporarily made visible and devtools forced open (reverted after; `git diff` on `ui/shell/tauri.conf.json` and `main.rs` is clean). No entry for `get_session` exists in `capabilities/default.json`. Rather than trust the GUI, checked the Core's own `invocation` table in the throwaway `kang.db`: two real `plan.generate` calls landed via HTTP, timestamped exactly when the build finished — which is only possible if `invoke("get_session")` succeeded first, since `client.ts`'s `callOperation` resolves the session before issuing any HTTP call. Corroborated by `netstat` showing 4 completed (TIME_WAIT) round-trips to the Core's port, matching `TodaysQuests.tsx`'s exact call pattern (plan.generate + task.get × N). **Conclusion: Tauri v2 does not require an explicit capabilities entry for this app-defined (non-plugin) command — it is invokable by default under the current config.** `capabilities/default.json` can be left as-is; no ADR or capability change needed for `get_session` itself. |
| NFR-011 overlay (global hotkey → standalone window) | **confirmed-resolved (2026-08-05, live launch)** | Built for real: a second Tauri window (`ui/shell/tauri.conf.json`'s `"capture"` window, `visible:false`, `decorations:false`, `alwaysOnTop`, `skipTaskbar`), its own Vite entry (`ui/capture.html` + `ui/src/capture-main.tsx` + `ui/src/capture/CaptureOverlay.tsx`), a real registered Ctrl+Shift+Space global shortcut (`main.rs`'s `capture_shortcut()` + `.with_handler(...)` + `app.global_shortcut().register(...)`), and a dedicated minimal capability file (`ui/shell/capabilities/capture.json`). Shared the actual `task.create` submit logic with the existing inline panel via a new `useQuickCapture` hook rather than reimplementing it, so the two entry points can't silently drift. Verified live, not by reasoning: booted a real Core + `cargo tauri dev`, sent a genuine OS-level Ctrl+Shift+Space via `keybd_event` (not a focused-window key event — this is what actually triggers a registered global hotkey) while Chrome had foreground focus. Confirmed via `Get-Process`/`GetForegroundWindow`: the "KANG — Quick Capture" window appeared and took focus, "KANG" (main) never appeared in the window list at any point, typing + Enter produced exactly one `task.create.dispatched` → `task.create.ok` in the Core's audit log with the row actually persisted in `kang.db`, the overlay window then hid itself (title reverted to WebView2's internal identifier) and focus moved to a different real app — satisfying 09_UI §3's "MUST NOT open the main window" and W2's "focus returns to whatever Kang was doing." One incidental finding while testing: a bare throwaway `KANG_HOME` with no `config/permissions.toml` fails closed (by design — `composition.py::_load_grants`, ADR-006) and silently blocks every event-publishing write; not a bug, but worth remembering for future live-launch tests — copy `config/defaults/permissions.toml` in first. |

**No discrepancy found between the prior session's final report and what's actually in the repo right now** — every claim in that report's "NOT verified, flagged rather than assumed" section checks out exactly as stated when re-verified independently just now. The one place worth being extra clear about (per the critique this handoff is responding to): the prior report's "Full loop confirmed" language for quick capture describes the `callOperation` → Core → DB round-trip, which **was** verified for real (confirmed again just now by static reading, and it's covered by the passing dispatch/schema tests) — it does **not** mean a human clicking through the actual rendered DOM was tested. The browser-tool viewport was broken (0×0, unreliable coordinates) during that verification, so the UI-interaction layer itself (open panel → type → press Enter, through real DOM events) has still never been exercised, only the API layer beneath it. That gap is real and remains open.

---

## 4. Next step

**Update (2026-08-05, same day, follow-up session):** both open architectural items in §3 are now resolved — see the updated rows above. The shell incident (§2) is also fully root-caused, not just worked around. Remaining M6 scope: the three other dashboard zones, the six remaining domains (only chrome buttons exist for them), the permission screen, and the confirm dialog. `held_action.*` handlers and their missing `commit_mode` remain genuinely open (unchanged).
