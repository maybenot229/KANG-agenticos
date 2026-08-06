import { useCompetitionCreate } from "./useCompetitionCreate";
import "./CompetitionForm.css";

/**
 * "New competition…" (ADR-014's UI, added 2026-08-06). Inline, non-modal
 * panel — 09_UI §3 reserves true modal dialogs for consequential
 * confirmations and destructive warnings only; tracking a competition is
 * neither. Mirrors `ProjectForm`'s shape exactly.
 */
export default function CompetitionForm({ onClose }: { onClose: () => void }) {
  const { name, setName, url, setUrl, state, submit } = useCompetitionCreate(() => {
    setTimeout(onClose, 600); // brief confirmation, then gone
  });

  return (
    <div className="competition-form" role="region" aria-label="New competition">
      {state.phase === "done" ? (
        <p className="competition-form__done">Tracked.</p>
      ) : (
        <>
          <input
            autoFocus
            className="competition-form__input"
            placeholder="Competition name…"
            value={name}
            disabled={state.phase === "submitting"}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
            }}
          />
          <input
            className="competition-form__input"
            placeholder="URL (optional)…"
            value={url}
            disabled={state.phase === "submitting"}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
            }}
          />
          <div className="competition-form__actions">
            <button
              type="button"
              className="competition-form__submit"
              disabled={state.phase === "submitting" || !name.trim()}
              onClick={() => submit()}
            >
              Track
            </button>
            <button
              type="button"
              className="competition-form__cancel"
              onClick={onClose}
            >
              Cancel
            </button>
          </div>
          {state.phase === "error" && (
            <p className="competition-form__error">{state.message}</p>
          )}
        </>
      )}
    </div>
  );
}
