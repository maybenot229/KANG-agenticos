import { GOAL_HORIZONS, useGoalCreate, type GoalHorizon } from "./useGoalCreate";
import "./GoalForm.css";

/**
 * "New goal…" (ADR-016's UI, added 2026-08-09). Inline, non-modal panel
 * — 09_UI §3 reserves true modal dialogs for consequential confirmations
 * and destructive warnings only; tracking a goal is neither. Mirrors
 * `ProjectForm`'s shape, with a `horizon` select added (mirroring
 * `DeadlineForm`'s `kind` select) since `horizon` is required, unlike
 * `ProjectForm`'s optional fields.
 */
export default function GoalForm({ onClose }: { onClose: () => void }) {
  const { title, setTitle, horizon, setHorizon, description, setDescription, state, submit } =
    useGoalCreate(() => {
      setTimeout(onClose, 600); // brief confirmation, then gone
    });

  return (
    <div className="goal-form" role="region" aria-label="New goal">
      {state.phase === "done" ? (
        <p className="goal-form__done">Tracked.</p>
      ) : (
        <>
          <input
            autoFocus
            className="goal-form__input"
            placeholder="Goal title…"
            value={title}
            disabled={state.phase === "submitting"}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
            }}
          />
          <select
            className="goal-form__select"
            aria-label="Horizon"
            value={horizon}
            disabled={state.phase === "submitting"}
            onChange={(e) => setHorizon(e.target.value as GoalHorizon)}
          >
            {GOAL_HORIZONS.map((h) => (
              <option key={h} value={h}>
                {h}
              </option>
            ))}
          </select>
          <input
            className="goal-form__input"
            placeholder="Description (optional)…"
            value={description}
            disabled={state.phase === "submitting"}
            onChange={(e) => setDescription(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
            }}
          />
          <div className="goal-form__actions">
            <button
              type="button"
              className="goal-form__submit"
              disabled={state.phase === "submitting" || !title.trim()}
              onClick={() => submit()}
            >
              Track
            </button>
            <button type="button" className="goal-form__cancel" onClick={onClose}>
              Cancel
            </button>
          </div>
          {state.phase === "error" && (
            <p className="goal-form__error">{state.message}</p>
          )}
        </>
      )}
    </div>
  );
}
