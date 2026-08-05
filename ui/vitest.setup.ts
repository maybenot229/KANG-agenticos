// ADR-012: jest-dom's matchers (toBeInTheDocument, toHaveFocus, etc.)
// registered globally so every test file gets them without repeating the
// import — the one exception to vitest.config.ts's `globals: false`
// choice, since these are DOM assertion matchers, not test-runner globals.
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// React Testing Library's auto-cleanup registers itself against the
// global `afterEach` vitest would otherwise provide — `globals: false`
// (deliberate, see vitest.config.ts) means that registration never
// happens on its own, so it's done explicitly here instead. Without
// this, a passing test can leave its render mounted and a later test in
// the same file gets "multiple elements found" against DOM the previous
// test never tore down (caught by this session's own first real run of
// this suite, not hypothetical).
afterEach(() => {
  cleanup();
});
