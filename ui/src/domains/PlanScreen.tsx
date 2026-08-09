import { useEffect, useState } from "react";
import { callOperation, newIdempotencyKey, ApiError } from "../api/client";
import type { PlanGenerateResponse } from "../generated/plan";
import type { TaskGetResponse } from "../generated/task";
import type { DeadlineListResponse } from "../generated/deadline";
import type { GoalListResponse } from "../generated/goal";
import GoalForm from "./GoalForm";
import "./PlanScreen.css";

/**
 * Plan domain (09_UI §2/UI-001): the fuller planning view, distinct from
 * the dashboard's Zone 1 summary. `plan.generate` already returns
 * `deadline_ids` and `calendar_event_ids` alongside `quest_ids` — Zone 1
 * only ever resolved the quests; this screen resolves the deadlines too
 * (via `deadline.list`, added for Zone 2, filtered client-side to the
 * plan's own ids — there is no `deadline.get`-by-id operation).
 *
 * Calendar events are named honestly, not resolved: `calendar_event_ids`
 * has no corresponding `calendar.get`/`calendar.list` operation in the
 * registry today, so this screen shows the count the Planner factored in
 * without fabricating titles it cannot actually fetch.
 *
 * Goals (`goal.list`, ADR-016, added 2026-08-09) live here rather than
 * under Projects: 02_PRODUCT_REQUIREMENTS §4's own framing groups "daily
 * quests, schedules, priorities, long-term goals" as one concept, and
 * `goal` is schema-independent of `project` (a project may optionally
 * point at a goal via `project.goal_id`, never the reverse) — unlike
 * `milestone`, which genuinely is a project's own sub-resource. Grouped
 * by horizon (quarter/year/life, 07_DATABASE §5.2's own three), each
 * group ordered title-then-id per `GoalStore.list_all()`'s contract, an
 * empty horizon shown as "None yet" rather than hidden — the same
 * honesty `ProjectsScreen`'s "No projects tracked yet" already gives an
 * empty domain.
 *
 * `goalFormOpen`/`onGoalFormOpenChange` are lifted to `App.tsx`
 * (mirroring `Attention.tsx`'s own lift for `DeadlineForm`, and
 * `ProjectsScreen`/`CompetitionsScreen`'s own lift for their forms) so
 * the palette's "New goal…" Act command can open this form from any
 * location, not just this screen's own "+ New goal" button.
 *
 * `Achieve`/`Revise`/`Retire` (added 2026-08-10, ADR-018/`goal.achieve`
 * `.revise`/`.retire`) appear only on `active` goals — the transition
 * operations reject any other starting status, so offering the buttons
 * on an already-terminal goal would be a control that always errors.
 * Re-fetches the goal list on success, same discipline every other
 * write on this screen already uses.
 */

const GOAL_HORIZONS = ["quarter", "year", "life"] as const;

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | {
      status: "ready";
      plan: PlanGenerateResponse;
      quests: TaskGetResponse[];
      deadlines: DeadlineListResponse["deadlines"];
    };

type GoalLoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; response: GoalListResponse };

export default function PlanScreen({
  goalFormOpen,
  onGoalFormOpenChange,
}: {
  goalFormOpen: boolean;
  onGoalFormOpenChange: (open: boolean) => void;
}) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [goalState, setGoalState] = useState<GoalLoadState>({ status: "loading" });
  const [transitioningGoalId, setTransitioningGoalId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const plan = await callOperation<PlanGenerateResponse>(
          "plan.generate",
          {},
          crypto.randomUUID(),
        );
        const [quests, deadlineList] = await Promise.all([
          Promise.all(
            plan.quest_ids.map((id) =>
              callOperation<TaskGetResponse>("task.get", { id }),
            ),
          ),
          callOperation<DeadlineListResponse>("deadline.list", {}),
        ]);
        const deadlines = deadlineList.deadlines.filter((d) =>
          plan.deadline_ids.includes(d.id),
        );
        if (!cancelled) setState({ status: "ready", plan, quests, deadlines });
      } catch (err) {
        if (cancelled) return;
        const message = err instanceof ApiError ? err.envelope.message : String(err);
        setState({ status: "error", message });
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  async function loadGoals(cancelledRef: { current: boolean }) {
    try {
      const response = await callOperation<GoalListResponse>("goal.list", {});
      if (!cancelledRef.current) setGoalState({ status: "ready", response });
    } catch (err) {
      if (cancelledRef.current) return;
      const message = err instanceof ApiError ? err.envelope.message : String(err);
      setGoalState({ status: "error", message });
    }
  }

  useEffect(() => {
    const cancelledRef = { current: false };
    loadGoals(cancelledRef);
    return () => {
      cancelledRef.current = true;
    };
  }, []);

  async function transitionGoal(id: string, operation: string) {
    setTransitioningGoalId(id);
    try {
      await callOperation(operation, { id }, newIdempotencyKey());
      await loadGoals({ current: false });
    } catch (err) {
      const message = err instanceof ApiError ? err.envelope.message : String(err);
      setGoalState({ status: "error", message });
    } finally {
      setTransitioningGoalId(null);
    }
  }

  if (state.status === "loading") {
    return <p className="plan__status">Loading the plan…</p>;
  }

  if (state.status === "error") {
    return <p className="plan__status plan__status--error">{state.message}</p>;
  }

  const { plan, quests, deadlines } = state;

  return (
    <section aria-label="Plan" className="plan">
      <h2 className="plan__heading">Plan — {plan.plan_date}</h2>

      <h3 className="plan__subheading">Quests</h3>
      {quests.length === 0 ? (
        <p className="plan__status">No quests scheduled today.</p>
      ) : (
        <ul className="plan__list">
          {quests.map((quest) => (
            <li key={quest.id} className="plan__item">
              <span className="plan__title">{quest.title}</span>
              <span className="plan__meta">
                priority {quest.priority} · {quest.status}
              </span>
            </li>
          ))}
        </ul>
      )}

      <h3 className="plan__subheading">Deadlines factored in</h3>
      {deadlines.length === 0 ? (
        <p className="plan__status">None.</p>
      ) : (
        <ul className="plan__list">
          {deadlines.map((deadline) => (
            <li key={deadline.id} className="plan__item">
              <span className="plan__title">{deadline.title}</span>
              <span className="plan__meta">
                {deadline.kind} · due {deadline.at}
              </span>
            </li>
          ))}
        </ul>
      )}

      <p className="plan__summary">
        {plan.estimated_minutes} min estimated
        {plan.deferred_count > 0 ? ` · ${plan.deferred_count} deferred` : ""}
        {plan.calendar_event_ids.length > 0
          ? ` · ${plan.calendar_event_ids.length} calendar event(s) factored in`
          : ""}
      </p>
      {plan.calendar_event_ids.length > 0 && (
        <p className="plan__note">
          Calendar event details aren't shown — no operation exists yet to
          fetch them by id.
        </p>
      )}

      <h3 className="plan__subheading">
        Goals
        <button
          type="button"
          className="plan__add"
          onClick={() => onGoalFormOpenChange(!goalFormOpen)}
        >
          + New goal
        </button>
      </h3>

      {goalFormOpen && (
        <GoalForm
          onClose={() => {
            onGoalFormOpenChange(false);
            loadGoals({ current: false }); // re-fetch: the tracked goal joins the list
          }}
        />
      )}

      {goalState.status === "loading" && <p className="plan__status">Loading…</p>}
      {goalState.status === "error" && (
        <p className="plan__status plan__status--error">{goalState.message}</p>
      )}
      {goalState.status === "ready" &&
        GOAL_HORIZONS.map((horizon) => {
          const goals = goalState.response.goals.filter((g) => g.horizon === horizon);
          return (
            <div key={horizon} className="plan__goal-group">
              <h4 className="plan__goal-horizon">{horizon}</h4>
              {goals.length === 0 ? (
                <p className="plan__status">None yet.</p>
              ) : (
                <ul className="plan__list">
                  {goals.map((goal) => (
                    <li key={goal.id} className="plan__goal-item">
                      <span className="plan__title">{goal.title}</span>
                      <span className="plan__meta">{goal.status}</span>
                      {goal.description && (
                        <span className="plan__description">{goal.description}</span>
                      )}
                      {goal.status === "active" && (
                        <span className="plan__goal-actions">
                          <button
                            type="button"
                            className="plan__goal-action"
                            disabled={transitioningGoalId === goal.id}
                            onClick={() => transitionGoal(goal.id, "goal.achieve")}
                          >
                            Achieve
                          </button>
                          <button
                            type="button"
                            className="plan__goal-action"
                            disabled={transitioningGoalId === goal.id}
                            onClick={() => transitionGoal(goal.id, "goal.revise")}
                          >
                            Revise
                          </button>
                          <button
                            type="button"
                            className="plan__goal-action"
                            disabled={transitioningGoalId === goal.id}
                            onClick={() => transitionGoal(goal.id, "goal.retire")}
                          >
                            Retire
                          </button>
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
    </section>
  );
}
