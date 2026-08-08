import { useState } from "react";
import { callOperation, newIdempotencyKey, ApiError } from "../api/client";
import type { MilestoneCreateResponse } from "../generated/milestone";

// `milestone.create`'s real UI entry point (ADR-015 — the Milestones sub-
// domain's first write path). Mirrors `useProjectCreate`'s exact shape.
// `project_id` is fixed by the caller (the project whose detail view this
// form is opened from), not a field Kang fills in — a milestone with no
// project context to create it from doesn't happen in this UI.
//
// `status` is not exposed, same reasoning as every other tracking-only
// form this session: no status-transition operation exists yet, so a
// picker for a value nothing downstream can act on would be a half-built
// affordance.

export type MilestoneCreateState =
  | { phase: "idle" }
  | { phase: "submitting" }
  | { phase: "done"; milestoneId: string }
  | { phase: "error"; message: string };

export function useMilestoneCreate(projectId: string, onDone: () => void) {
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [state, setState] = useState<MilestoneCreateState>({ phase: "idle" });

  function reset() {
    setTitle("");
    setDue("");
    setState({ phase: "idle" });
  }

  async function submit() {
    if (!title.trim()) return;
    setState({ phase: "submitting" });
    try {
      const result = await callOperation<MilestoneCreateResponse>(
        "milestone.create",
        { project_id: projectId, title, due: due || null },
        newIdempotencyKey(),
      );
      setState({ phase: "done", milestoneId: result.milestone_id });
      onDone();
    } catch (err) {
      const message = err instanceof ApiError ? err.envelope.message : String(err);
      setState({ phase: "error", message });
    }
  }

  return { title, setTitle, due, setDue, state, submit, reset };
}
