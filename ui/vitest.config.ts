import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// ADR-012: Vitest + React Testing Library, component-level DOM/keyboard-
// interaction tests only — jsdom, not a real browser (see the ADR's own
// Consequences for what this does and doesn't replace). Separate from
// vite.config.ts (which owns the Tauri dev-server/build shape, D002) since
// the two run for different reasons and this file's `test` block would be
// dead weight in every real dev/build invocation.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    globals: false, // explicit `import { describe, it, expect } from "vitest"` everywhere
  },
});
