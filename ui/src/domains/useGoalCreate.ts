import { useState } from "react";
import { callOperation, newIdempotencyKey, ApiError } from "../api/client";
import type { GoalCreateResponse } from "../generated/goal";

// `goal.create`'s real UI entry point (ADR-016 — the goal entity's first
// write path). Mirrors `useProjectCreate`'s exact shape, the same
// one-concept-one-implementation discipline applied to goals' own
// creation round trip.
//
// `status` is not exposed here, same reasoning as `useProjectCreate`:
// `goal.create` accepts one (defaulting to "active"), but there is no
// status-transition operation yet (achieve/revise/retire) — offering a
// picker for a value nothing downstream can later change would be a
// half-built affordance. Every goal this form creates starts `active`,
// honestly matching what the backend can do today.

export const GOAL_HORIZONS = ["quarter", "year", "life"] as const;
export type GoalHorizon = (typeof GOAL_HORIZONS)[number];

export type GoalCreateState =
  | { phase: "idle" }
  | { phase: "submitting" }
  | { phase: "done"; goalId: string }
  | { phase: "error"; message: string };

export function useGoalCreate(onDone: () => void) {
  const [title, setTitle] = useState("");
  const [horizon, setHorizon] = useState<GoalHorizon>("quarter");
  const [description, setDescription] = useState("");
  const [state, setState] = useState<GoalCreateState>({ phase: "idle" });

  function reset() {
    setTitle("");
    setHorizon("quarter");
    setDescription("");
    setState({ phase: "idle" });
  }

  async function submit() {
    if (!title.trim()) return;
    setState({ phase: "submitting" });
    try {
      const result = await callOperation<GoalCreateResponse>(
        "goal.create",
        {
          title,
          horizon,
          description: description.trim() || null,
        },
        newIdempotencyKey(),
      );
      setState({ phase: "done", goalId: result.goal_id });
      onDone();
    } catch (err) {
      const message = err instanceof ApiError ? err.envelope.message : String(err);
      setState({ phase: "error", message });
    }
  }

  return {
    title,
    setTitle,
    horizon,
    setHorizon,
    description,
    setDescription,
    state,
    submit,
    reset,
  };
}
