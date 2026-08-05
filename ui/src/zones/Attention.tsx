import { useEffect, useState } from "react";
import { callOperation, ApiError } from "../api/client";
import type { DeadlineListResponse } from "../generated/deadline";
import "./Attention.css";

/**
 * Zone 2 — "What needs attention?" (09_UI §4): deadline horizon
 * (competitions first), approval-queue count, health alerts.
 *
 * Only the deadline horizon has a real data source today —
 * `deadline.list` (added this session, exposing `DeadlineStore.active()`
 * through the API for the first time). The other two parts of this zone
 * are honest gaps, not features: the competitions domain is an empty
 * stub (`src/kang/domain/competitions/__init__.py` only), so "competitions
 * first" cannot be ordered against anything real yet; the approval queue
 * is `held_action.*`, registered in the contract but never wired to a
 * handler (confirmed-open, session-handoff 2026-08-05 §3); "health
 * alerts" names a concept 09_UI never defines. Rendering fabricated data
 * for any of these would violate 09_UI §4's "Empty states MUST be honest
 * and quiet" — so this zone says so plainly instead of pretending they
 * work.
 */

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; deadlines: DeadlineListResponse["deadlines"] };

export default function Attention() {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const response = await callOperation<DeadlineListResponse>(
          "deadline.list",
          {},
        );
        if (!cancelled) {
          setState({ status: "ready", deadlines: response.deadlines });
        }
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

  return (
    <section aria-label="What Needs Attention" className="attention">
      <h2 className="attention__heading">What Needs Attention</h2>

      {state.status === "loading" && (
        <p className="attention__status">Loading deadlines…</p>
      )}
      {state.status === "error" && (
        // 09_UI §13: the one honest sentence, verbatim, never synthesized.
        <p className="attention__status attention__status--error">
          {state.message}
        </p>
      )}
      {state.status === "ready" && state.deadlines.length === 0 && (
        <p className="attention__status">No deadlines currently tracked.</p>
      )}
      {state.status === "ready" && state.deadlines.length > 0 && (
        <ul className="attention__list">
          {state.deadlines.map((deadline) => (
            <li key={deadline.id} className="attention__item">
              <span className="attention__title">{deadline.title}</span>
              <span className="attention__meta">
                {deadline.kind} · due {deadline.at}
              </span>
            </li>
          ))}
        </ul>
      )}

      <p className="attention__note">
        Competitions tracking and the approval queue aren't available yet.
      </p>
    </section>
  );
}
