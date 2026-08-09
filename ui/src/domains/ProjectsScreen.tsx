import { useEffect, useState } from "react";
import { callOperation, ApiError } from "../api/client";
import type { ProjectListItem, ProjectListResponse } from "../generated/project";
import ProjectForm from "./ProjectForm";
import ProjectDetail from "./ProjectDetail";
import "./ProjectsScreen.css";

/**
 * Projects domain (09_UI §2/UI-001). Real now (added 2026-08-06, ADR-013)
 * — `project.create`/`.list` are the Projects domain's first operations,
 * tracking only per 03_ROADMAP's M4/M5 objective ("projects... tracking
 * only"). Clicking a project opens its detail view (added 2026-08-07,
 * ADR-015) — depth 2 of 09_UI §2's hub-and-spoke, showing that project's
 * milestones (see `ProjectDetail.tsx`). `goal` is a real operation now
 * (ADR-016) but has no UI surface yet — a real, separately-named gap
 * (no natural view location decided), not shown here.
 *
 * `formOpen`/`onFormOpenChange` are lifted to `App.tsx` (added
 * 2026-08-09, mirroring `Attention.tsx`'s own lift for `DeadlineForm`)
 * so the palette's "New project…" Act command can open this screen's
 * form from any location, not just this screen's own "+ New project"
 * button.
 *
 * `project.complete` (added 2026-08-10, ADR-018) lives inside
 * `ProjectDetail`, not here — see that file's own docstring for why.
 * `onProjectUpdated` closes the detail view and re-fetches this
 * screen's list so a completed project's status is reflected without a
 * stale row lingering.
 */

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; response: ProjectListResponse };

export default function ProjectsScreen({
  formOpen,
  onFormOpenChange,
}: {
  formOpen: boolean;
  onFormOpenChange: (open: boolean) => void;
}) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [selected, setSelected] = useState<ProjectListItem | null>(null);

  async function load(cancelledRef: { current: boolean }) {
    try {
      const response = await callOperation<ProjectListResponse>("project.list", {});
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

  if (selected) {
    return (
      <ProjectDetail
        project={selected}
        onBack={() => setSelected(null)}
        onProjectUpdated={() => {
          setSelected(null);
          load({ current: false }); // re-fetch: the completed project's status changed
        }}
      />
    );
  }

  return (
    <section aria-label="Projects" className="projects">
      <h2 className="projects__heading">
        Projects
        <button
          type="button"
          className="projects__add"
          onClick={() => onFormOpenChange(!formOpen)}
        >
          + New project
        </button>
      </h2>

      {formOpen && (
        <ProjectForm
          onClose={() => {
            onFormOpenChange(false);
            load({ current: false }); // re-fetch: the tracked project joins the list
          }}
        />
      )}

      {state.status === "loading" && <p className="projects__status">Loading…</p>}
      {state.status === "error" && (
        <p className="projects__status projects__status--error">{state.message}</p>
      )}
      {state.status === "ready" && state.response.projects.length === 0 && (
        <p className="projects__status">No projects tracked yet.</p>
      )}
      {state.status === "ready" && state.response.projects.length > 0 && (
        <ul className="projects__list">
          {state.response.projects.map((project) => (
            <li key={project.id}>
              <button
                type="button"
                className="projects__item"
                onClick={() => setSelected(project)}
              >
                <span className="projects__name">{project.name}</span>
                <span className="projects__meta">
                  {project.status}
                  {project.github_repo ? ` · ${project.github_repo}` : ""}
                </span>
                {project.description && (
                  <span className="projects__description">{project.description}</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}

      <p className="projects__note">
        Goals aren't shown yet — real schema exists (0006) but no
        operation reads them.
      </p>
    </section>
  );
}
