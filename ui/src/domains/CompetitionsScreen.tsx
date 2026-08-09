import { useEffect, useState } from "react";
import { callOperation, ApiError } from "../api/client";
import type { CompetitionListResponse } from "../generated/competition";
import CompetitionForm from "./CompetitionForm";
import "./CompetitionsScreen.css";

/**
 * Competitions domain (09_UI §2/UI-001). Real now (added 2026-08-06,
 * ADR-014) — `competition.create`/`.list` are the Competitions domain's
 * first operations, tracking only per 03_ROADMAP's M4/M5 objective
 * ("competitions... tracking only"), same scope line `project` was built
 * against (ADR-013).
 *
 * This screen's own previous docstring claimed "tracking and discovery
 * are both later-phase work (Phase 2)" — checked against `03_ROADMAP.md`
 * directly while drafting ADR-014, that over-stated the gap: discovery
 * (`evaluation`/`result`, the Scout pipeline) is genuinely Phase 2/M7;
 * tracking (a competition Kang already knows about) was always M4/M5
 * scope, just unbuilt until now. Corrected here rather than left to
 * silently contradict the roadmap it cited.
 *
 * `formOpen`/`onFormOpenChange` are lifted to `App.tsx` (added
 * 2026-08-09, mirroring `Attention.tsx`'s own lift for `DeadlineForm`)
 * so the palette's "New competition…" Act command can open this screen's
 * form from any location, not just this screen's own "+ New competition"
 * button.
 */

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; response: CompetitionListResponse };

export default function CompetitionsScreen({
  formOpen,
  onFormOpenChange,
}: {
  formOpen: boolean;
  onFormOpenChange: (open: boolean) => void;
}) {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  async function load(cancelledRef: { current: boolean }) {
    try {
      const response = await callOperation<CompetitionListResponse>(
        "competition.list",
        {},
      );
      if (!cancelledRef.current) setState({ status: "ready", response });
    } catch (err) {
      if (cancelledRef.current) return;
      const message = err instanceof ApiError ? err.envelope.message : String(err);
      setState({ status: "error", message });
    }
  }

  useEffect(() => {
    const cancelledRef = { current: false };
    load(cancelledRef);
    return () => {
      cancelledRef.current = true;
    };
  }, []);

  return (
    <section aria-label="Competitions" className="competitions">
      <h2 className="competitions__heading">
        Competitions
        <button
          type="button"
          className="competitions__add"
          onClick={() => onFormOpenChange(!formOpen)}
        >
          + New competition
        </button>
      </h2>

      {formOpen && (
        <CompetitionForm
          onClose={() => {
            onFormOpenChange(false);
            load({ current: false }); // re-fetch: the tracked competition joins the list
          }}
        />
      )}

      {state.status === "loading" && <p className="competitions__status">Loading…</p>}
      {state.status === "error" && (
        <p className="competitions__status competitions__status--error">
          {state.message}
        </p>
      )}
      {state.status === "ready" && state.response.competitions.length === 0 && (
        <p className="competitions__status">No competitions tracked yet.</p>
      )}
      {state.status === "ready" && state.response.competitions.length > 0 && (
        <ul className="competitions__list">
          {state.response.competitions.map((competition) => (
            <li key={competition.id} className="competitions__item">
              <span className="competitions__name">{competition.name}</span>
              <span className="competitions__meta">
                {competition.status}
                {competition.url ? ` · ${competition.url}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}

      <p className="competitions__note">
        Discovery and evaluation aren't built yet — the Scout pipeline is
        Phase 2 of the roadmap. Competitions here are tracked by hand.
      </p>
    </section>
  );
}
