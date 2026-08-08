import { useMilestoneCreate } from "./useMilestoneCreate";
import "./MilestoneForm.css";

/**
 * "New milestone…" (ADR-015's UI, added 2026-08-07). Inline, non-modal
 * panel — 09_UI §3 reserves true modal dialogs for consequential
 * confirmations and destructive warnings only; tracking a milestone is
 * neither. Mirrors `ProjectForm`/`DeadlineForm`'s shape exactly.
 */
export default function MilestoneForm({
  projectId,
  onClose,
}: {
  projectId: string;
  onClose: () => void;
}) {
  const { title, setTitle, due, setDue, state, submit } = useMilestoneCreate(
    projectId,
    () => {
      setTimeout(onClose, 600); // brief confirmation, then gone
    },
  );

  return (
    <div className="milestone-form" role="region" aria-label="New milestone">
      {state.phase === "done" ? (
        <p className="milestone-form__done">Tracked.</p>
      ) : (
        <>
          <input
            autoFocus
            className="milestone-form__input"
            placeholder="Milestone title…"
            value={title}
            disabled={state.phase === "submitting"}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
            }}
          />
          <input
            type="date"
            className="milestone-form__input"
            aria-label="Due (optional)"
            value={due}
            disabled={state.phase === "submitting"}
            onChange={(e) => setDue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
            }}
          />
          <div className="milestone-form__actions">
            <button
              type="button"
              className="milestone-form__submit"
              disabled={state.phase === "submitting" || !title.trim()}
              onClick={() => submit()}
            >
              Track
            </button>
            <button
              type="button"
              className="milestone-form__cancel"
              onClick={onClose}
            >
              Cancel
            </button>
          </div>
          {state.phase === "error" && (
            <p className="milestone-form__error">{state.message}</p>
          )}
        </>
      )}
    </div>
  );
}
