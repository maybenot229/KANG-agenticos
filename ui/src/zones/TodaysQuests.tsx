import { useEffect, useState } from "react";
import { callOperation, ApiError } from "../api/client";
import type { PlanGenerateResponse } from "../generated/plan";
import type { TaskGetResponse } from "../generated/task";
import "./TodaysQuests.css";

/**
 * Zone 1 — "What should I do?" (09_UI §4): Today's Quests, largest and
 * first in focus order. `plan.generate` (FR-001, the deterministic,
 * zero-model path) returns quest IDs only, not full task records — this
 * screen resolves each with a follow-up `task.get`, legitimate at the
 * 3-5-quest scale 09_UI §4 itself specifies ("Today's Quests (3–5, from
 * the Planner)"), not an N+1 concern worth optimizing away here.
 *
 * No degraded-mode marker is rendered: M5's Planner is zero-model by
 * construction (05 §16, verified by
 * suites/determinism/test_plan_determinism.py::test_no_model_or_clock_is_reachable_from_the_planner)
 * — "degraded" is an M7 (AI provider outage) concept that cannot occur
 * yet. Not an oversight; there is genuinely nothing to mark until M7
 * introduces a model call the Planner could fall back from.
 */

interface Quest extends TaskGetResponse {}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; quests: Quest[]; plan: PlanGenerateResponse };

export default function TodaysQuests() {
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
        const quests = await Promise.all(
          plan.quest_ids.map((id) =>
            callOperation<TaskGetResponse>("task.get", { id }),
          ),
        );
        if (!cancelled) setState({ status: "ready", quests, plan });
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
    return <p className="quests__status">Loading today's quests…</p>;
  }

  if (state.status === "error") {
    // 09_UI §13: error presentation — the one honest sentence, verbatim,
    // never a synthesized explanation (API-006's message contract).
    return <p className="quests__status quests__status--error">{state.message}</p>;
  }

  if (state.quests.length === 0) {
    // 09_UI §4: honest, quiet empty states — never motivational filler.
    return <p className="quests__status">No quests scheduled today.</p>;
  }

  return (
    <section aria-label="Today's Quests" className="quests">
      <h2 className="quests__heading">Today's Quests</h2>
      <ul className="quests__list">
        {state.quests.map((quest) => (
          <li key={quest.id} className="quests__item">
            <span className="quests__title">{quest.title}</span>
            <span className="quests__meta">
              priority {quest.priority} · {quest.status}
            </span>
          </li>
        ))}
      </ul>
      <p className="quests__summary">
        {state.plan.estimated_minutes} min estimated
        {state.plan.deferred_count > 0
          ? ` · ${state.plan.deferred_count} deferred`
          : ""}
      </p>
    </section>
  );
}
