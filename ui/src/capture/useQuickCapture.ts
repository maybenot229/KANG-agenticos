import { useRef, useState } from "react";
import { callOperation, newIdempotencyKey, ApiError } from "../api/client";
import type { TaskCreateResponse } from "../generated/task";

// Shared capture logic (09_UI §3, NFR-011): the actual `task.create` round
// trip is one concept with two entry points — the left-rail button (inline
// panel inside the main window, `QuickCapture.tsx`) and the global-hotkey
// overlay window (`CaptureOverlay.tsx`). Per the constitution's naming
// discipline, this is written once and shared rather than reimplemented per
// entry point, which would silently drift the two invocation paths apart.

export type CaptureState =
  | { phase: "idle" }
  | { phase: "submitting" }
  | { phase: "done"; elapsedMs: number }
  | { phase: "error"; message: string };

/**
 * `onDone` is the one thing that legitimately differs per entry point: the
 * inline panel collapses itself (state toggle), the overlay window hides
 * itself (a real OS window). Both are "gone" per NFR-011's wording; how
 * "gone" is achieved is the caller's concern, not this hook's.
 */
export function useQuickCapture(onDone: () => void) {
  const [title, setTitle] = useState("");
  const [state, setState] = useState<CaptureState>({ phase: "idle" });
  const startedAt = useRef<number>(performance.now());

  function reset() {
    setTitle("");
    setState({ phase: "idle" });
    startedAt.current = performance.now();
  }

  async function submit() {
    if (!title.trim()) return;
    setState({ phase: "submitting" });
    try {
      await callOperation<TaskCreateResponse>(
        "task.create",
        { title },
        newIdempotencyKey(),
      );
      const elapsedMs = performance.now() - startedAt.current;
      setState({ phase: "done", elapsedMs });
      onDone();
    } catch (err) {
      const message =
        err instanceof ApiError ? err.envelope.message : String(err);
      setState({ phase: "error", message });
    }
  }

  return { title, setTitle, state, submit, reset, startedAt };
}
