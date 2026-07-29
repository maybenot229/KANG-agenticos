# ADR-007 — UI shell: Tauri is committed for v0.1

**Status:** accepted
**Date:** 2026-07-28
**Decides:** `04_ARCHITECTURE.md` §20.2 (open question: "UI shell final call")
**Discharges:** `18_IMPLEMENTATION_MASTER_PLAN.md` §8.5 / §10 step 17 (pre-committed spike), risk I6
**Unblocks:** M6
**Supersedes / amends:** nothing. `04` §20.2 moves from open question to decided; `04`'s text is amended to cite this ADR.

---

## 1. Context

`04_ARCHITECTURE` §20.2 recorded the UI shell as **assumed Tauri, not decided**, with an explicit condition: validate global-hotkey and tray behaviour on Windows 11 in a spike *before* committing v0.1 UI work. `18` §9 carried the same item as risk **I6**, with the mitigation stated as "spike mandated before UI commitment; fallback decision (alternative shell) is an ADR, not a scramble."

M6 is the dashboard milestone. It builds quick capture (`09_UI` §3), the palette (`UI-002`), the four dashboard zones (`09_UI` §4), the permission screen and the confirm dialog — all of which sit on the shell. Building them against an unvalidated shell would violate `18` §1.4 (infrastructure precedes its consumer), and a shell replacement after M6 would discard UI-layer assumptions about hotkey semantics and tray lifecycle.

The spike was therefore run first, as a throwaway rig (`kang_tauri_spike/`, outside the repository, never merged), against five acceptance criteria derived from constitutional text rather than from taste.

---

## 2. Method — and why the evidence is Kang's, not the AI's

Two of the five criteria (**B**, focus-unbroken; **D**, tray resilience) are judgments about lived desktop behaviour. They are not machine-checkable, and an AI attesting to them from screenshots would produce a rigorous-looking verdict that is not evidence.

The protocol used instead:

1. Claude wrote the spike scaffold (deterministic, reviewable — Tauri 2.x, one global hotkey, one borderless overlay window, one tray icon with menu, a capture log, and a dual JS/Rust latency readout).
2. Kang built and ran it on the real Windows 11 machine, in **release** mode (dev mode was excluded deliberately: it alters tray and focus behaviour and would contaminate B and D).
3. Kang recorded observations per criterion in `CHECKLIST.md`.
4. Claude wrote this ADR from that checklist, citing Kang's rows. Nothing here is inferred from priors about how Tauri "usually" behaves.

---

## 3. Acceptance criteria and observed results

| # | Criterion | Source | Result |
|---|---|---|---|
| **A** | Global hotkey fires while another app has focus | `09_UI` §3, `U4` | **Pass** — fired consistently across multiple presses, in multiple focus contexts; no collision with existing OS or application shortcuts on the machine |
| **B** | Overlay appears without opening the main window; focus returns to what Kang was doing (W2) | `09_UI` §3 | **Pass (release)** — release build never opened the main window on hotkey or on launch. See §4.1 for a debug-only anomaly |
| **C** | Invoke → type → Enter → gone, measured < 5 s | `NFR-011` | **Pass** — three timed invocations, **3 s each**. Margin against the 5 s bar is 40% |
| **D** | Tray icon present; menu works; survives Explorer restart; lives in the tray | `D016` (background-lifecycle philosophy) | **Pass on three of four.** Icon present on launch; right-click menu opened and its items worked; **icon survived an `explorer.exe` restart without relaunch**. Start-at-login: **not tested** (§5.1) |
| **E** | No Windows-only dependency in *core* | `NFR-010` | **Confirmed by code inspection.** The shell calls only cross-platform Tauri surfaces (`tray-icon`, `global-shortcut`, `WindowEvent`, `Manager`), each with Linux/macOS implementations. No direct `windows-sys` or Win32 reach-through. Platform specificity is confined to the shell, where it belongs; nothing core-side is implicated |

---

## 4. Findings that the criteria did not anticipate

### 4.1 Debug build opened the main window once; release never did

On one **debug** launch the main window appeared unrequested — blank, full-size — separate from any hotkey press. It did not recur, and the **release** build never exhibited it across the session.

**Ruling: not disqualifying, and not silently dropped.** The release binary is the artifact the product ships and the one the criterion is about. A one-off debug-mode window-visibility difference is consistent with WebView2 initialising differently under debug and does not bear on W2 in the shipped path. It is recorded here rather than smoothed away so that if it reappears in M6 the precedent exists and this is the second sighting, not the first.

### 4.2 A second instance panics on hotkey registration — KANG needs single-instance enforcement

Launching the debug build while the release build was still resident produced:

```
Failed to setup app: error encountered during setup hook:
HotKey already registered: HotKey { mods: CONTROL | SHIFT, key: Space, ... }
```

This is correct OS behaviour — a global hotkey is a single-owner OS resource — but it surfaces a **real requirement that no constitutional document currently states**: KANG MUST enforce single-instance at the shell, or a second launch will crash on the hotkey and, worse, a second core could contend for `kang.db`.

This is a genuine gap, not a spike artifact. It is raised as a finding for M6 (§5.2), not decided here — this ADR's scope is the shell choice.

### 4.3 One scaffold defect, fixed, with no bearing on the verdict

The scaffold failed to compile initially: Tauri 2 moved `emit` behind the `Emitter` trait, which the scaffold did not import. A one-line fix. Recorded only so the build log is legible to a future reader; it says nothing about Tauri's suitability.

---

## 5. Decision

**Tauri is committed as KANG's v0.1 UI shell.** `04` §20.2 is closed. Risk **I6** is retired. M6 may commit UI work to this shell.

Four of five criteria passed outright; the fifth (E) is confirmed by inspection. The one incomplete row (start-at-login) is a *packaging* question, not a shell-capability question, and does not gate the decision — Tauri demonstrably lives in the tray and survives an Explorer restart, which is the hard part.

### 5.1 Carried forward as RESERVED — start-at-login

**RESERVED(trigger: M6 packaging, or first real daily-use week — whichever is first).** Start-at-login was not tested. It is a Windows registration concern (Task Scheduler or Startup Apps), independent of the webview and hotkey machinery this spike validated. `D016`'s "lives in the tray" expectation is only half-proven until KANG starts *itself*.

Registered in `03_ROADMAP` §8's RESERVED registry, alongside the three items already carried from M5, so it surfaces at every version-boundary review (`03` §9) rather than being forgotten because the ADR said "Feasible."

### 5.2 New finding for M6 — single-instance enforcement

Per §4.2, M6 MUST address second-launch behaviour. Two mechanisms exist (Tauri's single-instance plugin; a core-side lock on `%KANG_HOME%`), and the choice touches both the shell and the store — so it is **its own ADR at M6**, not an inline decision here. What this ADR fixes is only that the requirement is now *known and recorded*, having been discovered by running the thing rather than by reasoning about it.

---

## 6. Alternatives considered

| Option | Why rejected |
|---|---|
| **Electron** | Bundles Chromium per app: hundreds of MB against Tauri's single-digit, plus a heavier resident footprint for a tray-resident always-on process. Contradicts the local-first, low-ceremony posture of `00`/`01`, and the WebView2 runtime Tauri uses is already present on Windows 11 |
| **Native Win32 / WinUI** | Would deliver the best possible hotkey and tray fidelity — and would violate `NFR-010` by making the shell unportable, foreclosing the Linux/macOS option permanently in exchange for a criterion that Tauri already passed |
| **Web app + separate tray helper** | Splits the shell across two artifacts and two lifecycles for no gain; quick capture's <5 s budget (`NFR-011`) is hostile to a browser round-trip and a tab-focus dance |
| **Defer the decision past M6** | Rejected on constitutional grounds: `18` §8.5 pre-commits the spike, and `18` §1.4 forbids building a consumer on unvalidated infrastructure. Deferral does not remove the decision; it relocates the cost to a rewrite |

---

## 7. Consequences

**Accepted.**
- M6 may build the dashboard, palette, quick capture, permission screen, and confirm dialog on Tauri.
- The shell stays a **pure client** (`UI-P1`): everything above is chrome over the local API. Nothing in the shell holds truth. If Tauri is ever replaced, the replacement re-implements the same client contract and loses nothing (`AR8`) — the reason this decision is reversible in principle despite being committed in practice.
- Quick capture's 5 s budget has 40% margin at spike scale. Margin will erode as the real capture path (API call, permission check, store write, event publish) replaces the scaffold's file append. **`NFR-011` MUST be re-measured against the real path at the M6 gate** — this ADR proves the shell is not the bottleneck; it does not pre-clear the product path.

**Costs and open edges.**
- A Rust toolchain and MSVC Build Tools are now a hard prerequisite of the build environment. Worth naming: the toolchain install was the single largest time cost of this spike, and it is a one-time cost that a future contributor (or a rebuilt machine) pays again. It belongs in the repository's setup documentation.
- Start-at-login (§5.1) and single-instance (§5.2) are owed.

---

## 8. Evidence

`kang_tauri_spike/CHECKLIST.md`, completed by Kang 2026-07-28 from direct observation on the target machine. The spike tree itself is throwaway and is **not** merged: if any of it appears in M6, that is a defect — M6 starts a fresh Tauri project against the generated client (`12_API`), per `18` §3's M6 gate ("UI built on the generated client only; zero non-client imports").

---

*When code and this document disagree, one of them is wrong on purpose — file the ADR.*
