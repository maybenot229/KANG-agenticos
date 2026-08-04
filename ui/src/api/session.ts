// Session resolution (API-003) — pure API client (UI-P1): this file's only
// job is obtaining {host, port, token}, never inspecting or minting one.
//
// Production path: `invoke("get_session")` (ui/shell/src/main.rs) reads
// %KANG_HOME%/session.json, exactly as cli/kang_cli.py does on the Python
// side — the same session handshake, a different client.
//
// Dev-only fallback: the plain `npm run dev` Vite server has no Tauri IPC
// bridge (window.__TAURI_INTERNALS__ doesn't exist outside the real
// webview), so there is no invoke() to call. VITE_DEV_SESSION_* env vars,
// sourced from a real Core booted the same way tools/generate_ts_client.py
// boots one, let a screen be verified against real data during `npm run
// dev` without needing the full desktop shell running. Never present in a
// production build — see the guard below.

export interface Session {
  host: string;
  port: number;
  token: string;
}

function isTauriRuntime(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

async function getSessionFromTauri(): Promise<Session> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<Session>("get_session");
}

function getSessionFromDevEnv(): Session {
  const host = import.meta.env.VITE_DEV_SESSION_HOST;
  const port = import.meta.env.VITE_DEV_SESSION_PORT;
  const token = import.meta.env.VITE_DEV_SESSION_TOKEN;
  if (!host || !port || !token) {
    throw new Error(
      "Not running inside Tauri, and VITE_DEV_SESSION_HOST/PORT/TOKEN " +
        "are not set. Either run through the Tauri shell, or boot a " +
        "throwaway Core and export those three env vars for `npm run dev`.",
    );
  }
  return { host, port: Number(port), token };
}

export async function getSession(): Promise<Session> {
  if (isTauriRuntime()) {
    return getSessionFromTauri();
  }
  // Dev-only fallback — never reachable in a production build, since a
  // production build only ever runs inside the real Tauri webview, where
  // isTauriRuntime() is always true.
  return getSessionFromDevEnv();
}
