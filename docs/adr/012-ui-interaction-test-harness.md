# ADR-012 — UI-interaction test harness: Vitest + React Testing Library

**Status:** accepted
**Date:** 2026-08-05
**Decides:** the session handoff's Section 6 item 3 ("Automated UI-interaction test harness... may be worth a deliberate decision (and possibly a new dependency/ADR — Vitest + Testing Library or Playwright are the obvious candidates, neither currently in `ui/package.json`)").
**Affected documents:** `13_TESTING.md` §2.6 (names "UI: same API fixtures ⇒ same render tree" as a determinism-test class; this ADR is the tooling ruling that class was waiting for), `17_PROJECT_STRUCTURE.md` (no new top-level directory — see Consequences), `18_IMPLEMENTATION_MASTER_PLAN.md` §3 M6.
**Cites:** ADR-011 (the project's first Node-side dependency precedent and its E10-justification format, followed here), 11_CODING_STANDARDS §25 (E10 justification paragraph, framework adoption without an ADR is forbidden), 09_UI_DESIGN.md §7 (the confirm dialog's keyboard-focus/Escape contract — the concrete gap this ADR exists to close a test for).

---

## 1. Context

Every M6 UI session has shipped interactive behavior — quick capture's submit-on-Enter, the confirm dialog's mount-time focus-on-Deny and Escape-denies-in-one-keystroke, the command palette's Ctrl+K/Escape/Enter/arrow-key selection, the Invocations panel's row-expand toggle — and every one of them has been verified exactly one way: live, by hand, against a real Core in a real (or scripted) browser, this session and the ones before it. That discipline caught real bugs (two CSS overflow bugs at the shell's actual 800×600 size, a missing idempotency key, a size-lint violation) and is not being abandoned. But it leaves zero regression coverage: nothing catches a future edit that silently breaks "Deny holds focus on mount" or "Escape denies without asking why" except another live pass, and live passes don't run in CI.

`ui/package.json` currently has no test runner at all (ADR-011's own Consequences section named this gap explicitly when it landed the project's first Node-side dependency). `13_TESTING.md` §2.6 already names the test class this ADR fills in: *"UI: same API fixtures ⇒ same render tree (snapshot tests on the zone structure — UI-P5's mechanical check)"* — the class exists on paper; no tool has ever backed it.

---

## Ruling — the test runner + DOM library

### Options

**A — Vitest + `@testing-library/react` + `jsdom` (recommended).**

Vitest is Vite's own test runner (same config format, same transform pipeline `ui/`'s build already uses — zero new bundler to configure). `@testing-library/react` renders components into `jsdom` (an in-process, no-browser DOM implementation) and queries them the way a user would (by role, label, text) rather than by internal implementation detail.

- *For:* the natural continuation of a project that already chose Vite (ADR-007/D002's shell decision, and the Vite scaffold ADR-011 built on). No second bundler, no second config language — `vitest.config.ts` reuses the same `defineConfig` shape as `vite.config.ts`. Fast (in-process DOM, no real browser process to spawn per test — matches 13_TESTING §2.2's "< 2 min total, parallel" unit-test bar, not the slower integration tier). Directly answers the gap this ADR exists for: keyboard focus (`document.activeElement`), keydown handlers (Escape/Enter/arrows), conditional rendering (a row expanding) — all reachable through jsdom without a real rendering engine. Testing Library's query-by-role/label philosophy also happens to enforce accessible markup as a side effect (a real, if secondary, benefit — `aria-label`/`role` attributes already used throughout `ui/src/` per every component built this session).
- *Against:* jsdom is not a real browser — it does not lay out CSS, does not run a real compositor, and some real-browser quirks (the exact one this session's own handoff names: "the Browser pane's synthetic key-press action doesn't reliably reach focused inputs in this environment") have no jsdom equivalent to catch or miss, for better or worse. It cannot replace the live-verification discipline for anything CSS-layout-shaped (the two overflow bugs this session found were exactly this kind of gap, and no DOM-level test tool would have caught them) — this ADR does not claim otherwise.

**B — Playwright (real browser automation).**

Drives an actual browser (Chromium/Firefox/WebKit) against a running dev server, closer to what every live-verification pass this session already did by hand.

- *For:* real layout, real focus semantics, real keyboard event dispatch — would have caught the CSS overflow bugs this session found live, which Option A cannot. Closest tool to "automate exactly what we've been doing by hand."
- *Against:* needs a running app to drive — either the Vite dev server alone (fine for pure-client behavior) or, for anything touching `callOperation`, a live Core too (session handshake, real HTTP), which means CI would need to boot a throwaway Core per test run — real process-management surface, slower (13_TESTING §2.3's integration tier, not the unit tier: browser binaries alone add real minutes and real disk to install and cache in CI, atop `python -m pytest`'s existing budget). Heavier dependency (a full browser-automation toolchain, several browser binaries) for a first UI-test dependency, when the concrete named gaps (focus, keydown handling, conditional rendering) don't need a real compositor to catch. The CSS-layout class of bug Option A can't reach is real, but is also the class this session already catches by the standing live-verification discipline (§14 of the session handoff) — this ADR is choosing not to duplicate that discipline in CI today, not to abandon it.

**C — No harness; keep relying on live verification alone.**

- *For:* zero new dependency, zero new CI surface, matches the "boring technology" bar most literally.
- *Against:* this is the status quo the handoff flagged as worth revisiting three sessions running. Zero regression coverage on behavior that has already broken once mid-session this project (the missing idempotency key looked correct until a real click failed) — a future edit to `ConfirmDialog.tsx` could silently un-focus Deny or make Escape ask a question, and nothing but another live pass would ever notice. Rejected: the gap is real, not hypothetical, and the fix is cheap (Option A) relative to leaving it open indefinitely.

### Decision

**Adopt A — Vitest + `@testing-library/react` + `@testing-library/user-event` + `@testing-library/jest-dom` + `jsdom`.** Component-level interaction tests, not end-to-end browser tests: this harness proves "this component's DOM behavior is correct in isolation" (focus lands where it should, a keystroke does what it should, a click toggles what it should), backed by mocking `callOperation` per 12_API §1's own client boundary (mocking the one function every screen this session built already calls through, per `ui/src/api/client.ts` — no new seam invented for testability). It does not replace live verification against a real Core for end-to-end behavior, CSS layout at the shell's real window size, or anything Option B's own Consequences names — those stay exactly as disciplined as `docs/guides/session-handoff-2026-08-05-m6-continued.md` §5 already describes.

**Concretely:**
1. `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom` join `ui/package.json`'s `devDependencies` (E10-justified above; all five are the standard, most widely-used tools in this exact combination — no bespoke alternative considered, unlike ADR-011's harder case, since this is a solved, uncontested pairing in the React ecosystem).
2. Test files are colocated next to the component they test (`Palette.test.tsx` beside `Palette.tsx`), not a new top-level `ui/tests/` directory — Vitest's and this ecosystem's own convention, and avoiding a structural change `17_PROJECT_STRUCTURE.md` would otherwise need touching for (a colocated file is not a "new top-level structure" in that document's sense).
3. `ui/package.json` gains a `"test": "vitest run"` script (CI-mode, no watch) plus whatever `vitest.config.ts` the jsdom environment needs.
4. Coverage in this pass is scoped to the three concrete gaps the 2026-08-05 handoff named by name: quick capture's submit path (`useQuickCapture`), the confirm dialog's mount-focus/Escape contract, and the palette's Escape/Enter/arrow-key selection. This is a floor, not the whole UI surface — remaining screens (Invocations' row-expand, the deadline form, every domain shell) get the same treatment incrementally as they're touched, not retrofitted in one pass here (13_TESTING §2's own taxonomy is built up class-by-class, not completed in one PR anywhere else in this project either).

---

## Consequences

- **Second Node-side devDependency set**, after ADR-011's `json-schema-to-typescript`. Dev-time only — nothing shipped in `ui/dist` depends on any of these five packages (same "no runtime footprint" property ADR-011's own package has). Pinned `vitest@^2` (not the newer `^4`) specifically so it dedupes onto the project's existing `vite@5.4.21` rather than pulling a second, incompatible `vite@8` tree — `npm audit` reports one moderate dev-server-only advisory (`GHSA-67mh-4wv8-2f99`, esbuild's dev-server CORS issue) surfacing through this same `vite@5.4.21`/`esbuild@0.21.x` pin; it predates this ADR (the project's existing `vite@^5.4.21` in `package.json` already carried it) and is dev-time-only (esbuild's dev server ships in nobody's production build) — not fixed here, since the fix is a breaking `vite@8` major-version bump, a separate decision this ADR doesn't make.
- **`13_TESTING.md` §2.6's "UI: same API fixtures ⇒ same render tree" line now has a real tool behind it** — this ADR is that ruling, the same relationship ADR-011 had to `03_ROADMAP.md`'s RESERVED row.
- **No new top-level directory** — colocated `*.test.tsx` files, matching the ecosystem's own convention; `17_PROJECT_STRUCTURE.md`'s `ui/src/` entry needs no edit.
- **Still not a substitute for live verification.** Anything CSS-layout-shaped, anything touching a real Core over real HTTP, anything at the shell's actual window size — stays exactly as disciplined as before. A green `npm run test` is evidence of component-level DOM correctness, not evidence a screen actually works end-to-end; conflating the two would be exactly the "should work is not a state code can be delivered in" failure 14_CLAUDE.md §5 warns against.
- **Explicitly NOT decided here:**
  - Whether `npm run test` gets wired into a CI pipeline — no CI pipeline exists yet for this project at all (this repo runs local `pytest`/`ruff`/lint tool invocations by hand, not a hosted CI); wiring one in is separate scope, unblocked but undone by this ADR.
  - Coverage thresholds or a completeness bar for UI tests — 13_TESTING §5's "Metrics & Coverage Philosophy" governs this project's general stance (trend-tracked, not gate-blocking on an arbitrary percentage); nothing UI-specific is ruled here.
  - Whether Playwright is added later for real end-to-end coverage once a CI Core-boot story exists — Option B's rejection here is scoped to "not now, not for these three gaps," not "never."

---

*When code and this document disagree, one of them is wrong on purpose — file the ADR.*
