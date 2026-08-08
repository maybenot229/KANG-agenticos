import { useEffect, useState } from "react";
import { callOperation, ApiError } from "../api/client";
import type { ProjectListItem } from "../generated/project";
import type { MilestoneListResponse } from "../generated/milestone";
import MilestoneForm from "./MilestoneForm";
import "./ProjectDetail.css";

/**
 * Project detail (09_UI §2/UI-001's hub-and-spoke: domain → entity →
 * detail, depth 2 of the max 3). Added 2026-08-07 alongside ADR-015 —
 * the first depth-2 view any domain this session has built; every other
 * screen so far has been domain → list only, honest because nothing sat
 * a click deeper until milestones gave Projects something to click into.
 *
 * Real data only: milestones (`milestone.list`, tracking only). No
 * goal linkage shown — `goal` has real schema (0006) but no operation
 * reads it yet, same honest-gap treatment `ProjectsScreen`'s own note
 * already gives it.
 */

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; response: MilestoneListResponse };

export default function ProjectDetail({
  project,
  onBack,
}: {
  project: ProjectListItem;
  onBack: () => void;
}) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [formOpen, setFormOpen] = useState(false);

  async function load(cancelledRef: { current: boolean }) {
    try {
      const response = await callOperation<MilestoneListResponse>("milestone.list", {
        project_id: project.id,
      });
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
  }, [project.id]);

  return (
    <section aria-label={`Project: ${project.name}`} className="project-detail">
      <button type="button" className="project-detail__back" onClick={onBack}>
        ← Projects
      </button>

      <h2 className="project-detail__heading">{project.name}</h2>
      <p className="project-detail__meta">
        {project.status}
        {project.github_repo ? ` · ${project.github_repo}` : ""}
      </p>
      {project.description && (
        <p className="project-detail__description">{project.description}</p>
      )}

      <h3 className="project-detail__subheading">
        Milestones
        <button
          type="button"
          className="project-detail__add"
          onClick={() => setFormOpen((open) => !open)}
        >
          + New milestone
        </button>
      </h3>

      {formOpen && (
        <MilestoneForm
          projectId={project.id}
          onClose={() => {
            setFormOpen(false);
            load({ current: false }); // re-fetch: the tracked milestone joins the list
          }}
        />
      )}

      {state.status === "loading" && (
        <p className="project-detail__status">Loading…</p>
      )}
      {state.status === "error" && (
        <p className="project-detail__status project-detail__status--error">
          {state.message}
        </p>
      )}
      {state.status === "ready" && state.response.milestones.length === 0 && (
        <p className="project-detail__status">No milestones tracked yet.</p>
      )}
      {state.status === "ready" && state.response.milestones.length > 0 && (
        <ul className="project-detail__list">
          {state.response.milestones.map((milestone) => (
            <li key={milestone.id} className="project-detail__item">
              <span className="project-detail__title">{milestone.title}</span>
              <span className="project-detail__meta">
                {milestone.status}
                {milestone.due ? ` · due ${milestone.due}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
