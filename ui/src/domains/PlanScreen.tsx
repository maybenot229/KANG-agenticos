import { useEffect, useState } from "react";
import { callOperation, ApiError } from "../api/client";
import type { PlanGenerateResponse } from "../generated/plan";
import type { TaskGetResponse } from "../generated/task";
import type { DeadlineListResponse } from "../generated/deadline";
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
 */

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | {
      status: "ready";
      plan: PlanGenerateResponse;
      quests: TaskGetResponse[];
      deadlines: DeadlineListResponse["deadlines"];
    };

export default function PlanScreen() {
  const [state, setState] = useState<LoadState>({ status: "loading" });

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
    </section>
  );
}
