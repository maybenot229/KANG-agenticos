import { useEffect, useRef, type KeyboardEvent } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { useQuickCapture } from "./useQuickCapture";
import "./CaptureOverlay.css";

// The real NFR-011 path: global hotkey -> this standalone window -> gone,
// main window untouched (09_UI §3: "MUST NOT open the main window if
// invoked globally"; W2: "focus returns to whatever Kang was doing").
//
// This window is created once (ui/shell/tauri.conf.json), hidden by
// default, and shown/focused by the Rust-side hotkey handler
// (ui/shell/src/main.rs) rather than recreated per invocation — recreating
// a WebviewWindow on every hotkey press would burn into NFR-011's <5s
// budget for no benefit, since the window never needs fresh JS state
// beyond what `reset()` below already clears. Dismissing it hides it
// (`window.hide()`), not closes it, for the same reason.
//
// Shape informed by (not copied from, per ADR-007 §8) the M6-pre-work
// spike's overlay.html: one hidden borderless window, a Rust-emitted
// "shown" event that clears+focuses the input and starts the latency
// clock, Enter submits, Escape cancels — both routes end in the same
// `window.hide()`.
const SHOWN_EVENT = "quick-capture:shown";

export default function CaptureOverlay() {
  const inputRef = useRef<HTMLInputElement>(null);
  const { title, setTitle, state, submit, reset } = useQuickCapture(() => {
    void getCurrentWindow().hide();
  });

  useEffect(() => {
    const win = getCurrentWindow();
    const unlisten = win.listen(SHOWN_EVENT, () => {
      reset();
      inputRef.current?.focus();
    });
    return () => {
      void unlisten.then((f) => f());
    };
    // reset is stable (useQuickCapture doesn't recreate it per render in a
    // way that matters here); this effect is mount/unmount-scoped only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") submit();
    if (e.key === "Escape") void getCurrentWindow().hide();
  }

  return (
    <div className="overlay" role="region" aria-label="Quick capture">
      {state.phase === "done" ? (
        <p className="overlay__done">
          Captured in {Math.round(state.elapsedMs)}ms.
        </p>
      ) : (
        <>
          <input
            ref={inputRef}
            autoFocus
            className="overlay__input"
            placeholder="Quick capture… (Enter to save, Esc to cancel)"
            value={title}
            disabled={state.phase === "submitting"}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={onKeyDown}
          />
          {state.phase === "error" && (
            <p className="overlay__error">{state.message}</p>
          )}
        </>
      )}
    </div>
  );
}
