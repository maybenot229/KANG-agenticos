// KANG — Tauri shell packaging (D002, 17_PROJECT_STRUCTURE "ui/shell/").
//
// Pure client of the local API (UI-P1): this file holds no truth and
// computes no domain logic. It owns exactly three things — process
// lifecycle (single-instance, ADR-008), the global-hotkey plugin
// registration, and the tray/window chrome. Everything else is
// ui/src/'s concern (TS, against the generated API client).
//
// This is a fresh project against ADR-007/008, not a copy of
// kang_tauri_spike/ — per ADR-007 §8, none of the spike's code is
// reused verbatim; only its proven *shape* (which crates, which APIs)
// informs this build.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs;
use std::path::PathBuf;

use serde::Serialize;
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Emitter, Manager,
};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

/// The quick-capture hotkey (NFR-011, 09_UI §3). One definition, used both
/// to register it and to recognise it in the handler — Ctrl+Shift+Space
/// matches the M6 pre-work spike (ADR-007 §3 criterion A), which already
/// confirmed no collision with OS or application shortcuts on the target
/// machine; a different binding would need that check re-run.
fn capture_shortcut() -> Shortcut {
    Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::Space)
}

/// Event name the "capture" window listens for (`ui/src/capture/
/// CaptureOverlay.tsx`) to clear its input and restart NFR-011's latency
/// clock on every summon — the window is created once and shown/hidden
/// thereafter, never recreated per invocation, so without this the second
/// and later summons would show whatever was left over from the previous
/// capture.
const CAPTURE_SHOWN_EVENT: &str = "quick-capture:shown";

/// Show the overlay and hand focus to it — never touches "main" (09_UI
/// §3: "MUST NOT open the main window if invoked globally"). Hiding it
/// again (on Enter-success or Escape, both handled frontend-side via the
/// "capture" capability's allow-hide grant) is expected to return focus
/// to whatever Kang was doing (W2) the same way it did in the spike
/// (ADR-007 §3 criterion B) — plain window show/hide, no extra Win32
/// focus-restoration code, since none was needed there either.
fn show_capture_overlay(app: &tauri::AppHandle) {
    if let Some(win) = app.get_webview_window("capture") {
        let _ = win.show();
        let _ = win.set_focus();
        let _ = app.emit_to("capture", CAPTURE_SHOWN_EVENT, ());
    }
}

/// The session handshake (API-003): the Core writes `%KANG_HOME%/session.json`
/// with `{host, port, token}` at startup (composition.py::serve). The shell's
/// only job is handing that file's content to the frontend — it never mints,
/// inspects, or modifies a session itself (UI-P1: no truth in the shell).
#[derive(Serialize)]
struct Session {
    host: String,
    port: u16,
    token: String,
}

#[derive(Serialize)]
enum SessionError {
    KangHomeNotSet,
    SessionFileMissing(String),
    Malformed(String),
}

/// `KANG_HOME` resolution mirrors the Core's own convention exactly
/// (`adapters/config/env_config.py`'s `_ENV_VAR = "KANG_HOME"`) — the shell
/// resolves its own env, never the Core's config port (12_API §5's session
/// handshake is client-side, same rule `cli/kang_cli.py` already follows).
#[tauri::command]
fn get_session() -> Result<Session, SessionError> {
    let kang_home = std::env::var("KANG_HOME").map_err(|_| SessionError::KangHomeNotSet)?;
    let session_path: PathBuf = [&kang_home, "session.json"].iter().collect();
    let raw = fs::read_to_string(&session_path)
        .map_err(|e| SessionError::SessionFileMissing(e.to_string()))?;
    let parsed: serde_json::Value =
        serde_json::from_str(&raw).map_err(|e| SessionError::Malformed(e.to_string()))?;
    let host = parsed["host"]
        .as_str()
        .ok_or_else(|| SessionError::Malformed("missing 'host'".into()))?
        .to_string();
    let port = parsed["port"]
        .as_u64()
        .ok_or_else(|| SessionError::Malformed("missing 'port'".into()))? as u16;
    let token = parsed["token"]
        .as_str()
        .ok_or_else(|| SessionError::Malformed("missing 'token'".into()))?
        .to_string();
    Ok(Session { host, port, token })
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![get_session])
        // --- Single-instance enforcement (ADR-008 Part A/B) ---
        // MUST be the first plugin registered (the plugin's own
        // documented requirement) so it can intercept a second launch
        // before anything else initialises.
        .plugin(tauri_plugin_single_instance::init(
            |app, args, cwd| {
                handle_second_instance(app, args, cwd);
            },
        ))
        // --- Global shortcut plugin (registered second, per ADR-008) ---
        // The handler only reacts to `Pressed` (not `Released`) so one
        // physical key-down doesn't summon the overlay twice.
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, shortcut, event| {
                    if event.state() == ShortcutState::Pressed && *shortcut == capture_shortcut()
                    {
                        show_capture_overlay(app);
                    }
                })
                .build(),
        )
        .setup(|app| {
            // Binds the shortcut this run (ADR-008 Part A's single-instance
            // enforcement is what stops a second launch from panicking on
            // this exact call — see 4.2 in ADR-007's spike report).
            app.global_shortcut().register(capture_shortcut())?;

            let show = MenuItem::with_id(app, "show", "Show KANG", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &quit])?;

            // icons/ is populated and tauri.conf.json's `bundle.icon` names
            // real paths under it (see ui/shell/README.md), so
            // `default_window_icon()` always resolves here — the tray is
            // built unconditionally, per the revert this branch called for
            // once real icons landed.
            let icon = app
                .default_window_icon()
                .cloned()
                .expect("bundle.icon is populated (tauri.conf.json); default_window_icon() must resolve");
            let _tray = TrayIconBuilder::new()
                .icon(icon)
                .menu(&menu)
                .show_menu_on_left_click(true)
                .tooltip("KANG")
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "show" => {
                        if let Some(win) = app.get_webview_window("main") {
                            let _ = win.show();
                            let _ = win.set_focus();
                        }
                    }
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;

            // Decision 016: core lives in the tray, UI opens on demand.
            // The main window is configured `visible: false`
            // (tauri.conf.json) and is never shown on launch — only in
            // response to a real invocation (tray "Show", or eventually
            // the quick-capture hotkey / a forwarded second-instance
            // launch with real intent).

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running kang-shell");
}

/// ADR-008 Part B: a bare second launch (no args beyond the program's
/// own path) does nothing whatsoever — no window, no toast, no tray
/// flash, no sound, no log line a user would see. A launch carrying
/// real content (a future `kang://` deep link or a file-association
/// path) is forwarded to this handler instead of being silently
/// dropped, per ADR-008's "wired in from the start."
///
/// `forward_launch_context` is a stub: no deep-link source exists yet
/// to call it, so there is nothing real to do with the content beyond
/// recording that it arrived. Acting on it (routing to a dashboard
/// screen, focusing a specific entity) is dashboard/quick-capture
/// scope, not this task's.
fn handle_second_instance(app: &tauri::AppHandle, args: Vec<String>, cwd: String) {
    // args[0] is the program path itself; anything beyond that is
    // real launch content (a URL, a file path) rather than a bare
    // duplicate launch.
    if args.len() <= 1 {
        return;
    }
    forward_launch_context(app, &args, &cwd);
}

fn forward_launch_context(_app: &tauri::AppHandle, _args: &[String], _cwd: &str) {
    // Stub: no kang:// scheme registration or file-association exists
    // yet (both are separate decisions from ADR-008 — see ui/shell's
    // deferral note). This function exists so the forwarding seam is
    // real and callable now, per ADR-008's explicit "wired in from
    // the start," even though it currently has nothing to do.
}
