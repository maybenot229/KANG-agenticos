# ADR-008 — Single-instance enforcement at the KANG shell

**Status:** accepted
**Date:** 2026-07-29
**Amended:** 2026-08-10 — Part A2 implemented (see "A2 implementation" below); this document's own text is left otherwise unedited per ADR-001's amendment precedent (append, never rewrite history).
**Affected documents:** `04_ARCHITECTURE.md` Decision 016 (run model: "core starts at login, lives in the tray; UI opens on demand" — this ADR is what makes that model crash-safe), `17_PROJECT_STRUCTURE.md` (`ui/shell/` — the mechanism's likely home), `07_DATABASE.md` DB-001 (WAL/busy_timeout — cited, not reopened), `03_ROADMAP.md` §8 (gains a RESERVED registry row for the core-side half)
**Cites:** `docs/adr/007-ui-shell-decision.md` §4.2/§5.2 (the finding this ADR discharges), `NFR-010` (no Windows-only core dependency), `SEC-003`/`SEC-004` (authority model — cited to confirm this ADR does not touch it)
**Related:** [[007-ui-shell-decision.md]] (names this as owed; scope was deliberately excluded there)

---

## 1. Context

ADR-007 §4.2 recorded a crash during the Tauri feasibility spike: launching a
second process instance (debug build, while the release build was still
resident) produced

```
Failed to setup app: error encountered during setup hook:
HotKey already registered: HotKey { mods: CONTROL | SHIFT, key: Space, ... }
```

This is correct OS behaviour — a global hotkey is a single-owner OS resource
— but ADR-007 named the underlying requirement as unstated anywhere in the
constitution: **KANG MUST enforce single-instance at the shell, or a second
launch crashes on the hotkey and, worse, a second core could contend for
`kang.db`.** ADR-007 explicitly deferred the decision here (§5.2), because it
"touches both the shell and the store."

**What the spike actually proved, and what it didn't.** The spike ran two
full separate OS processes (`kang-spike.exe`, debug and release builds)
racing for the same global-hotkey registration. That is the failure mode
`04_ARCHITECTURE` Decision 016 already rules out by design — KANG's run model
is one resident process ("core starts at login, lives in the tray; UI opens
on demand"), not repeated full launches. So this ADR is about *guaranteeing*
Decision 016's assumption holds under a real second launch attempt (user
double-clicks the installer's shortcut again, a second login session starts
it, etc.) — not about the different, easier problem of "show the UI window
again while the core is already running," which is just a window-show call
and needs no new mechanism.

**What the spike did not test:** a real Python core was never part of the
spike — it is pure Rust/Tauri. So "a second core could contend for
`kang.db`" (ADR-007 §4.2) is a *named risk*, not an observed one. Checking
`src/kang/adapters/sqlite/connection.py`: `kang.db` runs WAL with
`busy_timeout=5000`, so two processes would not corrupt the database — they
would contend (blocking writes, then `SQLITE_BUSY` past 5s) — and worse,
**two live cores would each run their own scheduler, notifier, and event-bus
subscribers**, a split-brain automation problem (duplicate `morning_plan`
runs, duplicate notifications) that is a real risk distinct from corruption.
This ADR treats that as the harder of the two problems Part A must solve.

This ADR makes two decisions, bundled because they're coupled the same way
ADR-006's schedule-grammar and job-dispatch halves were: **where** the
enforcement lives (Part A), and **what happens** when a second launch is
detected (Part B).

---

## Part A — Where enforcement lives

### A. Options

**A1 — Shell-only: `tauri-plugin-single-instance`.**

Official Tauri v2 plugin (`tauri-apps/plugins-workspace`), confirmed current
as of this writing. Must be registered before any other plugin (a real
constraint against the spike's existing `global-shortcut` registration,
which would need to move second). Its callback already receives the second
launch's `args` and `cwd` — forwarding launch context to the first instance
is the plugin's default behavior, not extra work.

- *For:* solves the exact crash the spike observed, entirely inside
  `ui/shell/` (17 §... "we mostly don't touch" — D002), zero core changes,
  small and boring (E10).
- *Against:* only prevents a second **shell** process. If the Python core is
  ever launched independently of the shell (a dev running `kang` CLI/core
  directly while the shell is also running, or a future non-Tauri client),
  this does nothing — the `kang.db` contention risk survives untouched.

**A2 — Core-only: a lock file/socket under `%KANG_HOME%`.**

The Python core takes an exclusive OS-level lock (lockfile or a bound
loopback socket) on startup; a second core process detects the lock and
exits/reports rather than starting a second scheduler/bus.

- *For:* solves the actually-worse problem (split-brain automation, doubled
  jobs) regardless of which process launched the second core — shell,
  CLI, or anything else. Matches PS-002/D003's existing `%KANG_HOME%`
  ownership model; no new dependency (E10) if done as a plain lockfile.
- *Against:* does **not** fix the spike's observed crash — that crash is a
  Rust/Tauri global-hotkey collision, which happens before the shell would
  even get to check any core-side lock (the hotkey registration is shell
  startup, not core startup). A1 and A2 are not substitutes for each other.

**A3 — Both, layered (shell plugin + core-side lock).**

- *For:* each layer catches the failure mode the other can't — A1 stops
  the hotkey crash (shell-launched duplicates, the common real-world case:
  double-clicking a shortcut twice); A2 stops split-brain automation
  regardless of launch path. Neither is speculative: both have a named,
  evidenced failure mode (the spike's crash; ADR-007's named DB-contention
  risk), so this isn't the speculative-structure pattern `PS-006` rejects —
  it's two known problems, each getting its own known fix.
- *Against:* two mechanisms to maintain instead of one; a small amount of
  real surface. The core-side lock is unbuilt (no scheduler/core process
  exists in the spike to test it against), so its cost is currently
  theoretical, while A1's cost is proven-small (one plugin, spike-tested
  shape).

### A. Decision

**Adopt A3 — both layers.** A1 (`tauri-plugin-single-instance`) stops the
crash the spike actually observed; A2 (a core-side startup lock) stops the
worse, unobserved risk of two live cores running independent schedulers and
notifiers against the same `kang.db`. Neither substitutes for the other —
see each option's "Against" above — so adopting only one leaves a named,
real failure mode open on purpose, which this ADR does not accept.

### A. Implementation staging (read before scoping M6)

**A1 is implementable now, as part of M6's shell work.** The spike already
proved the shape (global-shortcut registration, tray, overlay) that
`tauri-plugin-single-instance` slots alongside — the only new constraint is
registering it first, before `global-shortcut`.

**A2 was specified by this ADR but not implementable at the time** — there
was no Python core startup/composition sequence to attach a startup lock
to; `kernel/runtime/composition.py` had no "check if already running"
concept. Registered as a `03_ROADMAP` §8 RESERVED entry (trigger: "the
core gains a real startup/composition sequence with a natural attachment
point"), same pattern as start-at-login (ADR-007 §5.1) — the decision was
already made here, only the attachment point was missing.

### A2 implementation (2026-08-10)

The trigger fired: `composition.py::build_core()`/`serve()` gained a real
boot sequence the prior day (the scheduler's boot catch-up), giving A2 the
attachment point it was waiting for — and a 2026-08-10 design session
(prompted by ADR-017's own admission that its pre-flight liveness check
is a narrow workaround, not the real fix) confirmed the trigger was
satisfied and this ADR's decision didn't need re-deriving, only building.

Implemented exactly as this ADR already specified — exclusive lock under
`%KANG_HOME%`, taken on core startup, released by the OS on process exit
by any means (clean shutdown or crash), no PID-file staleness window:

- `domain/ports/startup_lock.py` — `StartupLock` port, `AlreadyRunningError`.
- `adapters/os_windows/startup_lock.py` — `FileStartupLock`, an exclusive
  `msvcrt.locking()` region on `%KANG_HOME%/core.lock`. Windows-only code,
  correctly confined to `adapters/os_windows/` behind the port — NFR-010's
  "no Windows-only **core** dependency" is satisfied by the port boundary,
  not by this adapter itself being portable (a POSIX `fcntl.flock`
  sibling adapter would join it behind the same port if a POSIX build
  ever exists).
- `adapters/fakes/startup_lock.py` — `FakeStartupLock`, contract-tested
  identically against the real adapter (`tests/fixtures/
  startup_lock_contract.py`, 13 §2.3).
- `composition.py::build_core()` acquires the lock before opening
  `kang.db` or the eventlog — nothing else is touched if another Core
  already holds it. `Core.close()` releases it. `serve()` catches
  `AlreadyRunningError` and reports a one-line message to stderr with a
  non-zero exit — Part B's own "exits/reports" language, now true for
  the core half exactly as it already was for the shell half (A1).

Real subprocess proof (`tests/suites/replay/test_single_instance.py`,
mirroring `test_boot_catchup.py`'s own `_Server` shape): two genuine
`python -m kang.kernel.runtime.composition` processes against the same
real `%KANG_HOME%` — the second exits with code 1 and a stderr message
naming the lock, the first's own session handshake is byte-for-byte
untouched; after the first stops, a third process starts clean with no
manual cleanup, proving the OS-release guarantee rather than assuming it.

The RESERVED row this ADR proposed is retired from `03_ROADMAP` §8 —
implemented, not merely triggered.

---

## Part B — Behavior on a detected second launch

This is the one you asked me not to decide. Three real options, all
supported directly by what `tauri-plugin-single-instance` already delivers
(it hands the first instance the second launch's `args`/`cwd` for free —
none of these require extra plumbing beyond deciding what to do with what's
already provided):

**B1 — Silent exit.** Second launch does nothing visible; first instance
is untouched, no window change, nothing.

- *For:* simplest; matches "KANG lives in the tray, you don't think about
  it" (Decision 016's ambient posture). Never surprises with an unexpected
  window popping up.
- *Against:* if launched by accident and nothing visibly happens, a
  bewildered "did that even work?" is plausible — the calm-by-default
  philosophy (UI-P2) doesn't obviously say silence is *right* here, only
  that noise is wrong; total silence on a deliberate double-click could
  read as broken rather than calm.

**B2 — Focus/restore the existing window (or overlay).** Second launch
is treated as "bring KANG to me" — the tray-resident instance shows/focuses
its main window (or the quick-capture overlay, if that's what a hotkey-style
second invocation implies).

- *For:* matches ordinary desktop-app expectations (this is what most
  tray apps do); turns an "accidental" second launch into a useful action
  rather than a no-op; directly reuses the quick-capture focus-handling
  already proven in the spike (criterion B, W2 — focus discipline already
  works).
- *Against:* ambiguous *which* surface to show — main dashboard, or quick
  capture? Guessing wrong could violate W2 (focus unbroken) in the opposite
  direction: yanking focus when Kang didn't ask for it, if the second
  "launch" was actually unintentional (e.g., a stray Start-menu click).

**B3 — Forward launch context to the first instance** (args/cwd, per the
plugin's default callback), acted on meaningfully — e.g., a future
file-association or `kang://` deep-link launch gets routed to the resident
instance instead of failing.

- *For:* the plugin does this by default at no extra engineering cost;
  future-proofs file-association/deep-link launches (09_UI's palette
  already names `kang://domain/entity/detail` deep links as a requirement)
  without a second ADR later.
- *Against:* pure forwarding with no defined *behavior* for the common case
  (a bare, argument-less second launch) doesn't answer B1 vs B2 by itself
  — B3 is really "what do we do with the args once forwarded," which still
  needs a B1/B2-style answer for the no-args case. It's additive to B1 or
  B2, not a third alternative to them.

### B. Decision

**Adopt B1 — silent exit — for a bare, argument-less second launch.** A
second launch with no meaningful args/cwd (the ordinary case: someone
double-clicks the shortcut again, a second login session starts KANG a
second time) produces no visible effect whatsoever. Not a toast, not a tray
flash, not a sound, not a window. The first instance is completely
undisturbed. This was Kang's explicit product call, not an engineering
default — B2's "helpfully" focusing a window on every accidental duplicate
launch was considered and rejected in favor of true silence, matching
UI-P2's calm-by-default philosophy taken all the way rather than partway.

**B3 is wired in from the start, but only where it carries real intent.**
When the second launch actually carries meaningful `args`/`cwd` — a future
file-association or `kang://` deep-link invocation — the first instance
acts on that forwarded context (per 09_UI's already-stated deep-link
requirement). That is not a violation of "silent exit": a deep-link launch
is not a bare duplicate launch, it is a request with content, and KANG
acting on real content it was handed is not the kind of noise UI-P2 is
protecting against. The distinction is exact: **no args → nothing visible.
Real args/cwd → acted on.** There is no third, intermediate case.

---

## Consequences

**Ships at M6:**
- `ui/shell/`'s Tauri project gains `tauri-plugin-single-instance`,
  registered before `global-shortcut` (the plugin's own ordering
  requirement — a real constraint the spike's registration order must
  respect).
- A bare second shell-process launch exits silently: no window, no toast,
  no tray flash, no sound. The first instance is untouched.
- Any second launch carrying real `args`/`cwd` (file-association or
  `kang://` deep-link, once either exists) is forwarded to and acted on by
  the first instance, per 09_UI's existing deep-link requirement — this
  wiring exists from M6 onward even though no deep-link source calls it yet.
- No permission/authority change: this is process lifecycle, not a
  capability grant — `SEC-003`/`SEC-004` are unaffected and not reopened by
  this ADR.
- No schema change, no new event type, no new operation.

**Deferred at M6, implemented 2026-08-10 — see "A2 implementation" above:**
- The core-side startup lock under `%KANG_HOME%` (A2) did not ship at M6
  — no real core startup sequence existed to attach it to yet. It shipped
  once one did (`serve()`'s boot catch-up landing the day before gave it
  the attachment point), per this ADR's own decision, not re-decided.
- Between M6 and 2026-08-10, the split-brain risk A2 addresses (two live
  cores each running a scheduler/notifier against the same `kang.db`) was
  open in the narrow case of a core launched independently of the shell
  (e.g., a developer running the core directly via CLI while the shell is
  also running). This was accepted as a known, named gap for that window,
  not a silent one — the same discipline ADR-006 used for
  `job.timeout_s`.

---

*When code and this document disagree, one of them is wrong on purpose — file the ADR.*
