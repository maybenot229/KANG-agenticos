import { useEffect, useState } from "react";
import { callOperation, ApiError } from "../api/client";
import type { AuditListResponse } from "../generated/audit";
import "./ActivityPanel.css";

/**
 * Activity (09_UI §12, System domain): "the human-readable audit stream
 * (S5): time · principal · action · one-line reasoning · correlation
 * link." Added 2026-08-05 — `audit.list` exposes `AuditService.records()`
 * (already existed as a thin pass-through), current month by default.
 *
 * "MUST offer no edit or delete affordances whatsoever — not grayed-out,
 * absent": there is no button, menu, or handler anywhere in this
 * component that could mutate a record — only `<p>`/`<ul>` rendering.
 *
 * Filtering by principal/action-class/date (09_UI §12) is not built —
 * this shows the current month's stream, unfiltered, which is already
 * real and useful; adding filter controls is separate follow-up scope.
 */
type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; audit: AuditListResponse };

export default function ActivityPanel() {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const audit = await callOperation<AuditListResponse>("audit.list", {});
        if (!cancelled) setState({ status: "ready", audit });
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
    <section aria-label="Activity" className="activity">
      <h3 className="activity__heading">
        Activity
        {state.status === "ready" ? ` — ${state.audit.month}` : ""}
      </h3>

      {state.status === "loading" && <p className="activity__status">Loading…</p>}
      {state.status === "error" && (
        <p className="activity__status activity__status--error">{state.message}</p>
      )}
      {state.status === "ready" && state.audit.records.length === 0 && (
        <p className="activity__status">No activity this month.</p>
      )}
      {state.status === "ready" && state.audit.records.length > 0 && (
        <ul className="activity__list">
          {state.audit.records.map((record, i) => (
            <li key={i} className="activity__record">
              <span className="activity__at">{record.at}</span>
              <span className="activity__line">
                {record.principal} · {record.action}
                {record.correlation_id ? ` · ${record.correlation_id}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
