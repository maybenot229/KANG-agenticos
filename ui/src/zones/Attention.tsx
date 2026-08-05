import { useEffect, useState } from "react";
import { callOperation, ApiError } from "../api/client";
import type { DeadlineListResponse } from "../generated/deadline";
import type { HeldActionListItem, HeldActionListResponse } from "../generated/held_action";
import ConfirmDialog from "../common/ConfirmDialog";
import DeadlineForm from "./DeadlineForm";
import "./Attention.css";

/**
 * Zone 2 — "What needs attention?" (09_UI §4): deadline horizon
 * (competitions first), approval-queue count, health alerts.
 *
 * Two of the three parts have real data sources now: the deadline
 * horizon (`deadline.list`) and the approval queue (`held_action.list`
 * + `.approve`/`.cancel`, wired this session — confirmed-open in the
 * 2026-07-31 audit, closed 2026-08-05). Held actions "appear in Zone 2
 * with age" and open the 09_UI §7 confirm dialog on review (§7: "Held
 * actions... expire visibly, never silently" — `expires_at` is rendered,
 * not hidden). "Competitions first" still cannot be ordered against
 * anything real (the competitions domain is an empty stub); "health
 * alerts" names a concept 09_UI never defines. Both remain honest gaps.
 *
 * `deadline.create` gained its first real form here (added 2026-08-05,
 * handoff Section 6 item 2): `formOpen`/`onFormOpenChange` are lifted to
 * `App.tsx` (mirroring `captureOpen`'s own lift for `QuickCapture`) so
 * the palette's "New deadline…" Act command can open the same panel from
 * any screen, not just Zone 2's own "+ New deadline" button.
 */

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | {
      status: "ready";
      deadlines: DeadlineListResponse["deadlines"];
      heldActions: HeldActionListItem[];
    };

export default function Attention({
  formOpen,
  onFormOpenChange,
}: {
  formOpen: boolean;
  onFormOpenChange: (open: boolean) => void;
}) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [reviewing, setReviewing] = useState<HeldActionListItem | null>(null);

  async function load(cancelledRef: { current: boolean }) {
    try {
      const [deadlineResponse, heldActionResponse] = await Promise.all([
        callOperation<DeadlineListResponse>("deadline.list", {}),
        callOperation<HeldActionListResponse>("held_action.list", {}),
      ]);
      if (!cancelledRef.current) {
        setState({
          status: "ready",
          deadlines: deadlineResponse.deadlines,
          heldActions: heldActionResponse.held_actions,
        });
      }
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

  function onResolved() {
    setReviewing(null);
    load({ current: false }); // re-fetch: the approved/cancelled item drops off
  }

  return (
    <section aria-label="What Needs Attention" className="attention">
      <h2 className="attention__heading">What Needs Attention</h2>

      {state.status === "loading" && (
        <p className="attention__status">Loading…</p>
      )}
      {state.status === "error" && (
        // 09_UI §13: the one honest sentence, verbatim, never synthesized.
        <p className="attention__status attention__status--error">
          {state.message}
        </p>
      )}

      {state.status === "ready" && (
        <>
          <h3 className="attention__subheading">
            Approval queue{" "}
            {state.heldActions.length > 0 ? `(${state.heldActions.length})` : ""}
          </h3>
          {state.heldActions.length === 0 ? (
            <p className="attention__status">Nothing awaiting approval.</p>
          ) : (
            <ul className="attention__list">
              {state.heldActions.map((heldAction) => (
                <li key={heldAction.id} className="attention__item">
                  <span className="attention__title">{heldAction.action}</span>
                  <span className="attention__meta">
                    expires {heldAction.expires_at}
                  </span>
                  <button
                    type="button"
                    className="attention__review"
                    onClick={() => setReviewing(heldAction)}
                  >
                    Review
                  </button>
                </li>
              ))}
            </ul>
          )}

          <h3 className="attention__subheading">
            Deadlines
            <button
              type="button"
              className="attention__add-deadline"
              onClick={() => onFormOpenChange(!formOpen)}
            >
              + New deadline
            </button>
          </h3>
          {formOpen && (
            <DeadlineForm
              onClose={() => {
                onFormOpenChange(false);
                load({ current: false }); // re-fetch: the tracked deadline joins the horizon
              }}
            />
          )}
          {state.deadlines.length === 0 ? (
            <p className="attention__status">No deadlines currently tracked.</p>
          ) : (
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
        </>
      )}

      <p className="attention__note">
        Competitions tracking isn't available yet; "health alerts" isn't a
        defined concept yet either.
      </p>

      {reviewing && (
        <ConfirmDialog heldAction={reviewing} onResolved={onResolved} />
      )}
    </section>
  );
}
