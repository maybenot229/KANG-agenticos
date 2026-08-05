import {
  useDeadlineCreate,
  SELF_STANDING_KINDS,
  type DeadlineKind,
} from "./useDeadlineCreate";
import "./DeadlineForm.css";

/**
 * "New deadline…" (09_UI §4 Zone 2 / palette Act register, added
 * 2026-08-05). Inline, non-modal panel — 09_UI §3 reserves true modal
 * dialogs for consequential confirmations and destructive warnings only;
 * tracking a deadline is neither. Mirrors `QuickCapture`'s shape exactly.
 *
 * `kind` only ever offers `custom`/`school` (see `useDeadlineCreate`'s own
 * docstring for why) — not a truncated dropdown standing in for a richer
 * one, an honest reflection of what `deadline.create` can accept today
 * without a competition/project to anchor to.
 */
export default function DeadlineForm({ onClose }: { onClose: () => void }) {
  const { title, setTitle, at, setAt, kind, setKind, state, submit } =
    useDeadlineCreate(() => {
      setTimeout(onClose, 600); // brief confirmation, then gone
    });

  return (
    <div className="deadline-form" role="region" aria-label="New deadline">
      {state.phase === "done" ? (
        <p className="deadline-form__done">Tracked.</p>
      ) : (
        <>
          <input
            autoFocus
            className="deadline-form__input"
            placeholder="Deadline title…"
            value={title}
            disabled={state.phase === "submitting"}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
            }}
          />
          <input
            type="datetime-local"
            className="deadline-form__input"
            aria-label="Due at"
            value={at}
            disabled={state.phase === "submitting"}
            onChange={(e) => setAt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
            }}
          />
          <select
            className="deadline-form__select"
            aria-label="Kind"
            value={kind}
            disabled={state.phase === "submitting"}
            onChange={(e) => setKind(e.target.value as DeadlineKind)}
          >
            {SELF_STANDING_KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
          <div className="deadline-form__actions">
            <button
              type="button"
              className="deadline-form__submit"
              disabled={state.phase === "submitting" || !title.trim() || !at}
              onClick={() => submit()}
            >
              Track
            </button>
            <button type="button" className="deadline-form__cancel" onClick={onClose}>
              Cancel
            </button>
          </div>
          {state.phase === "error" && (
            <p className="deadline-form__error">{state.message}</p>
          )}
          <p className="deadline-form__note">
            Only self-standing kinds (custom, school) are offered — the rest
            need a competition or project to anchor to, and neither domain
            exists yet.
          </p>
        </>
      )}
    </div>
  );
}
