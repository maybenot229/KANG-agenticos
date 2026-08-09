# ADR-017 — Activating RESERVED: start-at-login via a Windows Startup shortcut

**Status:** accepted
**Date:** 2026-08-09
**Decides:** activates the RESERVED registry row `03_ROADMAP.md` §8 names — *"Start-at-login (Windows registration — Task Scheduler or Startup Apps — independent of the webview/hotkey machinery the Tauri spike validated) | Trigger: M6 packaging, or first real daily-use week — whichever is first | ADR-007 §5.1"*. This session is that trigger: `tools/kang_start.ps1` (2026-08-09) is real, in-use, and Kang has been running KANG against his real, persistent `KANG_HOME` this same session — "first real daily-use week," not M6 packaging, is what's satisfied first.
**Affected documents:** `03_ROADMAP.md` §8 (this row retires), `docs/adr/007-ui-shell-decision.md` §5.1 (the deferral this ADR closes), `docs/adr/008-single-instance-enforcement.md` (cited, not superseded — see §4 below).
**Cites:** ADR-007 §5.1 (the exact deferral, and its own citation of `04_ARCHITECTURE` D016 — "core starts at login, lives in the tray"), ADR-008 (single-instance enforcement — the shell half is already real via `tauri_plugin_single_instance`; the core half stays RESERVED, and this ADR does not build it, only works around its absence for the one new risk auto-start introduces), CLAUDE.md §4 (RESERVED activation requires an ADR, never a commit message).

---

## 1. Context

`tools/kang_start.ps1` (this session, prior commit) is a manual, stopgap launcher: run it, it boots the real Core against `%KANG_HOME%` and opens the shell. It is not the real D016 run model ("core starts at login, lives in the tray") — Kang has to remember to run it by hand, every time, after every restart.

ADR-007 §5.1 named exactly this gap and deliberately deferred it: *"Start-at-login was not tested. It is a Windows registration concern (Task Scheduler or Startup Apps), independent of the webview and hotkey machinery this spike validated."* Its trigger — `RESERVED(trigger: M6 packaging, or first real daily-use week — whichever is first)` — is satisfied now: Kang has been running the real Core against his real, persistent `KANG_HOME` this session, with real tasks/project/milestones from prior sessions and real interaction (creating goals, completing a task) through the actual desktop window. M6 packaging (a single installer, D016) has not happened and is not a prerequisite this ADR needs — the trigger is an *or*, and daily use is what's real first.

### A new risk auto-start introduces, not present in the manual launcher

The shell already has real single-instance protection: `ui/shell/src/main.rs` registers `tauri_plugin_single_instance` — a second `kang-shell.exe` launch is intercepted, not a crash (this is the exact fix for the hotkey-re-registration crash ADR-007 §4.2's spike hit). **The Python Core has no equivalent.** `tools/kang_start.ps1` always starts a fresh Core process; run it twice, and two Cores exist, both able to open the same `kang.db` (SQLite's WAL mode tolerates concurrent connections, so this is not silently catastrophic) but both independently able to run the scheduler's boot catch-up (ADR from 2026-08-09, `serve()`'s new call) and both racing to write `session.json` last. Manual use made this an unlikely accident (Kang would notice a second PowerShell window). **Auto-start removes that accident-prevention**: Kang could forget KANG already started at login and run the launcher again by hand.

ADR-008 (still proposed) is the real, general fix — a file-based startup lock under `%KANG_HOME%`, core-side, for any launch path. This ADR does not build that; it is a bigger, separate decision (RESERVED in its own right, trigger: "the core gains a real startup/composition sequence with a natural attachment point" — arguably also satisfied now, but a distinct ruling from this one). What this ADR *does* do: give the launcher a cheap, narrow pre-flight check — before starting a new Core, ask whether the existing `session.json` already names a live one, and skip straight to opening the shell if so. Not a lock (nothing stops two launches racing at the exact same instant), but it closes the actual scenario auto-start creates (Kang logs in, the Startup shortcut fires, Kang later double-clicks the shortcut again out of habit).

---

## Ruling

### Options — the registration mechanism

**A — A shortcut in the Windows Startup folder (`shell:startup`) (recommended).**

- *For:* the simplest mechanism Windows offers, zero new dependencies, a single `.lnk` file, trivially reversible (delete the shortcut — no service to uninstall, no scheduled task to find and remove). Matches this project's own "boring tech" bar (11_CODING §17) exactly as well as Task Scheduler would for the one thing needed here (run one command at login), without Task Scheduler's extra surface (triggers, conditions, retry policies, an XML definition to maintain) — none of which this stopgap needs. `tools/kang_start.ps1` already exists and already does the right thing when double-clicked; a Startup shortcut just runs it without a human doing the double-click.
- *Against:* Startup-folder items are less discoverable/configurable than a Task Scheduler entry (no "run 5 minutes after login," no retry-on-failure) — irrelevant here; login-time is exactly when this should fire, and retry-on-failure is not a real requirement for a personal single-user app.

**B — A Task Scheduler entry (logon trigger).**

- *For:* more configurable (delay, run-whether-logged-in-or-not, failure actions); the option ADR-007 §5.1 also named.
- *Against:* heavier for what this needs — an XML task definition, `schtasks`/`Register-ScheduledTask` to create and remove it, more moving parts than a shortcut for the identical outcome ("run this command at login"). The real D016 packaged installer may reasonably choose Task Scheduler later (an MSI/installer conventionally registers one), but that is a separate, larger decision this stopgap should not anticipate. Rejected for now — not a real capability KANG needs today.

### Decision

**Adopt A.** A `.lnk` shortcut in `shell:startup`, targeting a new hidden-window variant of the existing launcher (`tools/kang_start_hidden.vbs`, a two-line VBScript wrapper — the standard, dependency-free way to launch a PowerShell script with zero visible window, since `powershell.exe -WindowStyle Hidden` alone still flashes a console window on some Windows builds). The shortcut is created by a new `tools/kang_register_autostart.ps1` (idempotent — safe to re-run, overwrites its own prior shortcut) and removed by `tools/kang_unregister_autostart.ps1`. Neither runs automatically; Kang runs the register script once, by hand, the same explicit-install-step spirit ADR-007/D016 already hold.

**The pre-flight guard** (closing the new double-launch risk, §1 above): `tools/kang_start.ps1` gains a check — if `%KANG_HOME%/session.json` exists, try `registry.get` against the host/port it names (a cheap, already-real query operation, no scope required); if it answers, a Core is already live, skip straight to launching the shell; if it doesn't (stale file, crashed process), proceed to start a fresh Core exactly as before.

---

## Consequences

- **`03_ROADMAP.md` §8's RESERVED row for start-at-login retires** — trigger satisfied, this ADR is the ruling it was waiting for.
- **Two new scripts** (`tools/kang_register_autostart.ps1`, `tools/kang_unregister_autostart.ps1`) plus a hidden-launch wrapper (`tools/kang_start_hidden.vbs`) — dev-tooling-shaped, not core/src, no import-contract exposure.
- **`tools/kang_start.ps1` gains a pre-flight liveness check** — the one piece of the double-launch risk this ADR closes narrowly; the general core-side startup lock (ADR-008) stays RESERVED and unbuilt, a real, separate gap this ADR does not pretend to close.
- **Still not the real D016 model**: no single packaged installer, no uninstall-removes-the-Startup-entry-automatically story (that's what `kang_unregister_autostart.ps1` is for, run by hand) — this is Kang's own machine, registered once, not shipped to anyone else.
- **What gets easier:** KANG is actually resident from login onward, matching D016's "core starts at login, lives in the tray" for the first time — the tray icon fix, the launcher, and boot catch-up (all this session) now compose into something that behaves like the real product, not a manually-driven demo.

---

*When code and this document disagree, one of them is wrong on purpose — file the ADR.*
