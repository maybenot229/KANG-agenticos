/// <reference types="vite/client" />

interface ImportMetaEnv {
  // Dev-only session fallback (ui/src/api/session.ts) — never set in a
  // production build, since production always runs inside the real
  // Tauri webview and never reaches this branch.
  readonly VITE_DEV_SESSION_HOST?: string;
  readonly VITE_DEV_SESSION_PORT?: string;
  readonly VITE_DEV_SESSION_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
