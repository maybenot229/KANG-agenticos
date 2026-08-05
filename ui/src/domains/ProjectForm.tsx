import { useProjectCreate } from "./useProjectCreate";
import "./ProjectForm.css";

/**
 * "New project…" (ADR-013's UI, added 2026-08-06). Inline, non-modal panel
 * — 09_UI §3 reserves true modal dialogs for consequential confirmations
 * and destructive warnings only; tracking a project is neither. Mirrors
 * `DeadlineForm`'s shape exactly.
 */
export default function ProjectForm({ onClose }: { onClose: () => void }) {
  const {
    name,
    setName,
    description,
    setDescription,
    githubRepo,
    setGithubRepo,
    state,
    submit,
  } = useProjectCreate(() => {
    setTimeout(onClose, 600); // brief confirmation, then gone
  });

  return (
    <div className="project-form" role="region" aria-label="New project">
      {state.phase === "done" ? (
        <p className="project-form__done">Tracked.</p>
      ) : (
        <>
          <input
            autoFocus
            className="project-form__input"
            placeholder="Project name…"
            value={name}
            disabled={state.phase === "submitting"}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
            }}
          />
          <input
            className="project-form__input"
            placeholder="Description (optional)…"
            value={description}
            disabled={state.phase === "submitting"}
            onChange={(e) => setDescription(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
            }}
          />
          <input
            className="project-form__input"
            placeholder="GitHub repo, owner/name (optional)…"
            value={githubRepo}
            disabled={state.phase === "submitting"}
            onChange={(e) => setGithubRepo(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
            }}
          />
          <div className="project-form__actions">
            <button
              type="button"
              className="project-form__submit"
              disabled={state.phase === "submitting" || !name.trim()}
              onClick={() => submit()}
            >
              Track
            </button>
            <button type="button" className="project-form__cancel" onClick={onClose}>
              Cancel
            </button>
          </div>
          {state.phase === "error" && (
            <p className="project-form__error">{state.message}</p>
          )}
        </>
      )}
    </div>
  );
}
