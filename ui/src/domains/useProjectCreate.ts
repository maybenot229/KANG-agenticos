import { useState } from "react";
import { callOperation, newIdempotencyKey, ApiError } from "../api/client";
import type { ProjectCreateResponse } from "../generated/project";

// `project.create`'s real UI entry point (ADR-013 — the Projects domain's
// first write path). Mirrors `useDeadlineCreate`'s exact shape (09_UI §4's
// deadline form), the same one-concept-one-implementation discipline
// applied to projects' own creation round trip.
//
// `status` is not exposed here: `project.create` accepts one (defaulting
// to "active"), but there is no status-change operation yet — offering a
// picker for a value nothing downstream can later change would be a
// half-built affordance. Every project this form creates starts `active`,
// honestly matching what the backend can do today.

export type ProjectCreateState =
  | { phase: "idle" }
  | { phase: "submitting" }
  | { phase: "done"; projectId: string }
  | { phase: "error"; message: string };

export function useProjectCreate(onDone: () => void) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [githubRepo, setGithubRepo] = useState("");
  const [state, setState] = useState<ProjectCreateState>({ phase: "idle" });

  function reset() {
    setName("");
    setDescription("");
    setGithubRepo("");
    setState({ phase: "idle" });
  }

  async function submit() {
    if (!name.trim()) return;
    setState({ phase: "submitting" });
    try {
      const result = await callOperation<ProjectCreateResponse>(
        "project.create",
        {
          name,
          description: description.trim() || null,
          github_repo: githubRepo.trim() || null,
        },
        newIdempotencyKey(),
      );
      setState({ phase: "done", projectId: result.project_id });
      onDone();
    } catch (err) {
      const message = err instanceof ApiError ? err.envelope.message : String(err);
      setState({ phase: "error", message });
    }
  }

  return {
    name,
    setName,
    description,
    setDescription,
    githubRepo,
    setGithubRepo,
    state,
    submit,
    reset,
  };
}
