import { useState } from "react";
import { callOperation, newIdempotencyKey, ApiError } from "../api/client";
import type { DeadlineCreateResponse } from "../generated/deadline";

// `deadline.create`'s real UI entry point (added 2026-08-05 — the 2026-08-05
// handoff's Section 6 item 2: "deadline.create has no UI form... deadlines
// can only be created via direct API calls"). Mirrors `useQuickCapture`'s
// shape exactly (09_UI §3's task-capture hook), the same one-concept-one-
// implementation discipline applied to deadlines' own creation round trip.

export const SELF_STANDING_KINDS = ["custom", "school"] as const;

// Only the self-standing kinds (07 §5.2/`deadline_service.py`'s
// `_SELF_STANDING_KINDS`) are offered: "registration"/"submission"/"event"
// all require a `competition_id`/`project_id` to anchor to, and both the
// Competitions and Projects domains are still empty stubs — there is
// nothing yet for this form to let Kang pick. Offering those three kinds
// now would let the form accept input the domain layer always rejects;
// the form's own choices stay honest about what the backend can actually
// do today, not what 07_DATABASE eventually names.
export type DeadlineKind = (typeof SELF_STANDING_KINDS)[number];

export type DeadlineCreateState =
  | { phase: "idle" }
  | { phase: "submitting" }
  | { phase: "done"; deadlineId: string }
  | { phase: "error"; message: string };

export function useDeadlineCreate(onDone: () => void) {
  const [title, setTitle] = useState("");
  const [at, setAt] = useState("");
  const [kind, setKind] = useState<DeadlineKind>("custom");
  const [state, setState] = useState<DeadlineCreateState>({ phase: "idle" });

  function reset() {
    setTitle("");
    setAt("");
    setKind("custom");
    setState({ phase: "idle" });
  }

  async function submit() {
    if (!title.trim() || !at) return;
    setState({ phase: "submitting" });
    try {
      const result = await callOperation<DeadlineCreateResponse>(
        "deadline.create",
        { title, at, kind },
        newIdempotencyKey(),
      );
      setState({ phase: "done", deadlineId: result.deadline_id });
      onDone();
    } catch (err) {
      const message = err instanceof ApiError ? err.envelope.message : String(err);
      setState({ phase: "error", message });
    }
  }

  return { title, setTitle, at, setAt, kind, setKind, state, submit, reset };
}
