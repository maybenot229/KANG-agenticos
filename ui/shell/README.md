# ui/shell/ — KANG's Tauri packaging

Constitutional home: `17_PROJECT_STRUCTURE.md` (`ui/shell/` — "Tauri (Rust)
packaging — 'we mostly don't touch' (D002)"), `docs/adr/007-ui-shell-decision.md`,
`docs/adr/008-single-instance-enforcement.md`.

This is a **fresh project**, not the spike. Per ADR-007 §8 ("the spike tree
itself is throwaway and is not merged: if any of it appears in M6, that is a
defect"), nothing here is copied from `kang_tauri_spike/` — only its proven
*shape* (which crates, which APIs actually worked on Windows 11) informed
this build.

## Build status: `cargo check` attempted, blocked on the icon gap

`cargo`/`rustc`/`cargo-tauri` **are** installed on this machine
(`~/.cargo/bin`) — an earlier session note claiming no Rust toolchain was
a `PATH` artifact (that shell didn't include `~/.cargo/bin`), corrected
once `~/.cargo/bin` was put on `PATH` and `cargo --version`/`cargo tauri
--version` were run.

`cargo check` was run against this project. First attempt failed on a
real mistake in `Cargo.toml`: `tauri-build` had been pinned to `2.11.5`,
wrongly assuming it shares `tauri`'s version number — Tauri's workspace
crates version independently. Fixed to `tauri-build = "2.6.3"` (verified
live against crates.io, matching how every other pin in this project was
verified).

After that fix, dependency resolution succeeded and **every dependency
compiled cleanly** — `tauri`, `tauri-build`, `tauri-plugin-single-instance`,
`tauri-plugin-global-shortcut`, and the full transitive tree. The build
then failed in `kang-shell`'s own build script:

```
icons/icon.ico` not found; required for generating a Windows Resource
file during tauri-build
```

**This is the icon gap below, but harder than it first looked.**
`tauri-build`'s build script unconditionally requires `icons/icon.ico` to
exist on Windows, at compile time, to embed as the executable's resource
icon — regardless of `tauri.conf.json`'s `bundle.icon` being `[]`. It is
not a soft, tray-only runtime concern; it is a hard `cargo check`/`cargo
build` failure. **This project does not compile yet, and won't until a
real `icon.ico` exists** — see below for why that isn't a quick fix. No
attempt was made to build past it (no placeholder icon synthesized, no
build-script workaround) — producing an actual icon file is a real
decision (see below), not something to route around silently.

`cargo tauri build` / `cargo tauri dev` have not been attempted — no
point, given `cargo check` itself doesn't pass yet. MSVC Build Tools'
presence is still unconfirmed (the failure happens before linking, in the
build script), so that remains an open question too.

## Known open item: `icons/` does not exist — now a confirmed hard build blocker

`tauri.conf.json`'s `bundle.icon` is deliberately `[]`, and there is no
`icons/` directory. `cargo tauri icon <source.png>` (the standard generator)
**is available** on this machine — confirmed via `cargo tauri --version`
— so the blocker is not toolchain availability. The blocker is that there
is no source image to feed it: the only 1024×1024 source that exists
anywhere in this repo's history is `icon-source.png`, committed on the
`spike/tauri-windows-shell` branch — which this task was explicitly told
not to reuse (it's spike-adjacent, and whether it's even the *right* icon
for the real product is Kang's call, not an engineering default).

`cargo check` (see Build status above) confirmed this is a **hard
compile-time failure**, not just a runtime tray-icon concern: `tauri-build`
requires `icons/icon.ico` unconditionally on Windows. This project will
not compile until a real, non-spike icon source exists.

`src/main.rs`'s tray-building code accounts for this: it checks
`app.default_window_icon()` and skips building the tray entirely if no
icon resolves, rather than hard-failing `.setup()`. That branch exists
**only** because of this gap and should be reverted to an unconditional
tray build once real icons land — it is not general-purpose error
handling.

**Next step, when Kang decides on a real icon:** `cargo tauri icon
<path-to-real-source.png>` from this directory, once a real (non-spike)
1024×1024 source PNG exists.

## Known open item: quick-capture hotkey is not bound

`tauri-plugin-global-shortcut` is registered (ADR-008 Part A ordering:
after single-instance, before anything else that might need it), but no
concrete shortcut is registered and no handler exists. Binding an actual
hotkey and deciding what it invokes is quick-capture behaviour (`09_UI`
§3) — dashboard-task scope, deliberately not this task's.

## Single-instance behaviour (ADR-008)

Implemented in `src/main.rs`: `tauri_plugin_single_instance` is the first
plugin registered. A bare second launch (no args beyond the program path)
does nothing visible at all — no window, no toast, no tray flash, no
sound (ADR-008 Part B, B1). A second launch carrying real `args`/`cwd` is
forwarded to `forward_launch_context()`, currently a stub — no `kang://`
scheme or file-association registration exists yet to call it, so there
is nothing real to act on. The seam exists now so a future deep-link
source has somewhere to arrive (ADR-008's "wired in from the start").

**Not built here (confirmed out of scope by ADR-008 itself):** the
core-side startup lock under `%KANG_HOME%` (ADR-008 Part A's other half).
It is specified but deferred to a `03_ROADMAP` §8 RESERVED entry, triggered
when the Python core gains a real startup sequence.
