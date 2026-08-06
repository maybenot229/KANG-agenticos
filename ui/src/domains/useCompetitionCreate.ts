import { useState } from "react";
import { callOperation, newIdempotencyKey, ApiError } from "../api/client";
import type { CompetitionCreateResponse } from "../generated/competition";

// `competition.create`'s real UI entry point (ADR-014 — the Competitions
// domain's first write path). Mirrors `useProjectCreate`'s exact shape.
//
// `status` is not exposed here, same reasoning as `useProjectCreate`'s own
// note: `competition.create` accepts one (defaulting to "discovered"), but
// no status-transition operation exists yet. `evaluation`/`result` aren't
// exposed either — those are Phase 3's own write path (07 §5.2's comment
// on the table), not something this form can honestly offer.

export type CompetitionCreateState =
  | { phase: "idle" }
  | { phase: "submitting" }
  | { phase: "done"; competitionId: string }
  | { phase: "error"; message: string };

export function useCompetitionCreate(onDone: () => void) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [state, setState] = useState<CompetitionCreateState>({ phase: "idle" });

  function reset() {
    setName("");
    setUrl("");
    setState({ phase: "idle" });
  }

  async function submit() {
    if (!name.trim()) return;
    setState({ phase: "submitting" });
    try {
      const result = await callOperation<CompetitionCreateResponse>(
        "competition.create",
        { name, url: url.trim() || null },
        newIdempotencyKey(),
      );
      setState({ phase: "done", competitionId: result.competition_id });
      onDone();
    } catch (err) {
      const message = err instanceof ApiError ? err.envelope.message : String(err);
      setState({ phase: "error", message });
    }
  }

  return { name, setName, url, setUrl, state, submit, reset };
}
