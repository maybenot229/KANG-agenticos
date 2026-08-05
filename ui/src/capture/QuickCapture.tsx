import { useQuickCapture } from "./useQuickCapture";
import "./QuickCapture.css";

/**
 * Quick capture, inline-panel entry point (09_UI §3): the left-rail button
 * inside the main window opens this while the dashboard is already in
 * focus. Reachable-from-every-screen, not the global-hotkey path — see
 * `CaptureOverlay.tsx` for that (NFR-011's standalone overlay window).
 *
 * NOT a modal: 09_UI §3 permits modal dialogs for exactly two things —
 * consequential confirmations (§7) and destructive-action warnings.
 * Quick capture is neither, so it renders as a non-modal inline panel,
 * not a `<dialog>`-style overlay that blocks the rest of the screen.
 */
export default function QuickCapture({ onClose }: { onClose: () => void }) {
  const { title, setTitle, state, submit } = useQuickCapture(() => {
    setTimeout(onClose, 600); // brief confirmation, then gone
  });

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
