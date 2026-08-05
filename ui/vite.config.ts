import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// KANG UI (D002: React + TypeScript, Tauri shell — 04_ARCHITECTURE Decision
// 002). Pure API client (UI-P1): this config's only job is bundling; it has
// no knowledge of the Core's ports, stores, or domain logic.
//
// Tauri v2 + Vite conventions (ui/shell/tauri.conf.json):
// - devUrl points here (http://localhost:1420); strictPort so a silently
//   different port never leaves the shell pointed at nothing.
// - Vite's own file-watcher must ignore ui/shell/target (Rust build output;
//   watching it would mean a `cargo build` triggers a frontend HMR storm).
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    watch: {
      ignored: ["**/shell/target/**"],
    },
  },
  build: {
    outDir: "dist",
    // Tauri's own minifier disagreement note: keep sourcemaps for debug
    // builds only, per Tauri's quickstart guidance — kept minimal here
    // since KANG has no bundle-size budget documented yet (not invented).
    sourcemap: true,
    rollupOptions: {
      // Two windows (ui/shell/tauri.conf.json: "main" + "capture"), two
      // independent HTML entry points — the NFR-011 overlay window loads
      // capture.html, never index.html's full dashboard bundle.
      // Plain relative paths (not an absolute `resolve(__dirname, ...)`)
      // deliberately — that would need @types/node just for path typing,
      // a new dependency this config doesn't otherwise need. Vite
      // resolves these against its own root (this file's directory) with
      // no extra configuration.
      input: {
        main: "index.html",
        capture: "capture.html",
      },
    },
  },
});
