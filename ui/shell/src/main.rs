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

use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Manager,
};

fn main() {
    tauri::Builder::default()
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
        // No shortcut is bound here: which key and what it invokes is
        // quick-capture behaviour (09_UI §3), a separate, later task.
        // This registers the plugin only, so the ordering constraint
        // is real and testable now, without inventing capture behaviour.
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .setup(|app| {
            let show = MenuItem::with_id(app, "show", "Show KANG", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &quit])?;

            // icons/ is a known, named open item (no source asset exists
            // yet — see ui/shell/README.md): tauri.conf.json's `bundle.icon`
            // is deliberately empty, so `default_window_icon()` is expected
            // to return None until real icons land. Building the tray is
            // skipped rather than hard-failed in that case — this branch
            // exists solely because of that documented gap, not as a
            // general-purpose error swallow, and must be revisited (tray
            // unconditionally built) once icons/ is populated.
            if let Some(icon) = app.default_window_icon().cloned() {
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
            }

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
