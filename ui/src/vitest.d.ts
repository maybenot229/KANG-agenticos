// ADR-012: makes jest-dom's Vitest matchers (toBeInTheDocument, toHaveFocus,
// etc.) visible to `tsc -b` across every test file under src/ without a
// per-file import — the runtime registration itself happens once in
// vitest.setup.ts; this is the type-only half of the same thing.
/// <reference types="@testing-library/jest-dom/vitest" />
