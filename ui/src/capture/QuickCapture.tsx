import { useRef, useState } from "react";
import { callOperation, newIdempotencyKey, ApiError } from "../api/client";
import type { TaskCreateResponse } from "../generated/task";
import "./QuickCapture.css";

/**
 * Quick capture (09_UI §3): reachable from every screen, invoke → type →
 * enter → gone, < 5s end-to-end (NFR-011).
 *
 * NOT a modal: 09_UI §3 permits modal dialogs for exactly two things —
 * consequential confirmations (§7) and destructive-action warnings.
 * Quick capture is neither, so it renders as a non-modal inline panel,
 * not a `<dialog>`-style overlay that blocks the rest of the screen.
 *
 * Known, flagged limitation of this slice: the real architecture is a
 * standalone Tauri overlay WINDOW triggered by a global hotkey, which
 * "MUST NOT open the main window" and returns focus to whatever Kang was
 * doing (W2) — that is a second WebviewWindow + global-shortcut binding
 * on the Rust side, not built this session (see the session report).
 * This component proves the interaction + real API round-trip half of
 * NFR-011's budget; it does not prove the global-hotkey-to-overlay-close
 * path, which needs the actual desktop shell running to measure for real.
 */

type CaptureState =
  | { phase: "idle" }
  | { phase: "submitting" }
  | { phase: "done"; elapsedMs: number }
  | { phase: "error"; message: string };

export default function QuickCapture({ onClose }: { onClose: () => void }) {
  const [title, setTitle] = useState("");
  const [state, setState] = useState<CaptureState>({ phase: "idle" });
  const startedAt = useRef<number>(performance.now());

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
      setTimeout(onClose, 600); // brief confirmation, then gone
    } catch (err) {
      const message = err instanceof ApiError ? err.envelope.message : String(err);
      setState({ phase: "error", message });
    }
  }

  return (
    <div className="capture" role="region" aria-label="Quick capture">
      {state.phase === "done" ? (
        <p className="capture__done">
          Captured in {Math.round(state.elapsedMs)}ms.
        </p>
      ) : (
        <>
          <input
            autoFocus
            className="capture__input"
            placeholder="Capture a task…"
            value={title}
            disabled={state.phase === "submitting"}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
              if (e.key === "Escape") onClose();
            }}
          />
          {state.phase === "error" && (
            <p className="capture__error">{state.message}</p>
          )}
        </>
      )}
    </div>
  );
}
