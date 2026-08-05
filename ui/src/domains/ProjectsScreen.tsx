import { useEffect, useState } from "react";
import { callOperation, ApiError } from "../api/client";
import type { ProjectListResponse } from "../generated/project";
import ProjectForm from "./ProjectForm";
import "./ProjectsScreen.css";

/**
 * Projects domain (09_UI §2/UI-001). Real now (added 2026-08-06, ADR-013)
 * — `project.create`/`.list` are the Projects domain's first operations,
 * tracking only per 03_ROADMAP's M4/M5 objective ("projects... tracking
 * only"). `milestone`/`goal` are real schema too (0006) but have no
 * operation yet; this screen shows projects only, honestly.
 */

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; response: ProjectListResponse };

export default function ProjectsScreen() {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [formOpen, setFormOpen] = useState(false);

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

  return (
    <section aria-label="Projects" className="projects">
      <h2 className="projects__heading">
        Projects
        <button
          type="button"
          className="projects__add"
          onClick={() => setFormOpen((open) => !open)}
        >
          + New project
        </button>
      </h2>

      {formOpen && (
        <ProjectForm
          onClose={() => {
            setFormOpen(false);
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
            <li key={project.id} className="projects__item">
              <span className="projects__name">{project.name}</span>
              <span className="projects__meta">
                {project.status}
                {project.github_repo ? ` · ${project.github_repo}` : ""}
              </span>
              {project.description && (
                <span className="projects__description">{project.description}</span>
              )}
            </li>
          ))}
        </ul>
      )}

      <p className="projects__note">
        Milestones and goals aren't shown yet — real schema exists (0006)
        but no operation reads them.
      </p>
    </section>
  );
}
