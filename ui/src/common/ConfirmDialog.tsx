import { useEffect, useRef, useState } from "react";
import { callOperation, newIdempotencyKey, ApiError } from "../api/client";
import type { HeldActionListItem } from "../generated/held_action";
import "./ConfirmDialog.css";

/**
 * The confirmation dialog (09_UI §7) — "the most safety-critical UI."
 * Constitutional rules this component exists to satisfy, each named so a
 * future edit doesn't accidentally undo one:
 *
 * - **One action, one dialog.** Renders exactly one `held_action`'s
 *   what/who/why/reversibility (12_API §7's fields, verbatim — no
 *   summarizing, no rephrasing). No batching, no "approve all", no
 *   remember-my-choice affordance exists anywhere in this component (S1).
 * - **Visually unique.** Its own distinct look (`--color-critical`
 *   border and heading, never `--color-accent`) so it can never be
 *   reflex-clicked from habit with any other dialog in the app —
 *   `CaptureOverlay`'s blue accent theme is deliberately not reused here.
 * - **Confirm is never the default-focused element.** `autoFocus`/the
 *   mount-time `.focus()` call both land on Deny, never Approve — no
 *   Enter-through to the consequential action.
 * - **Denial is one keystroke and never asks why.** Escape (from
 *   anywhere in the dialog, since the handler sits on the backdrop and
 *   keydown bubbles) or a single click on Deny both cancel immediately;
 *   neither prompts for a reason.
 */
export default function ConfirmDialog({
  heldAction,
  onResolved,
}: {
  heldAction: HeldActionListItem;
  onResolved: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const denyRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    denyRef.current?.focus();
  }, []);

  async function resolve(operation: "held_action.approve" | "held_action.cancel") {
    setBusy(true);
    setError(null);
    try {
      // Both are commands (registry idempotency: "key-required", API-004) —
      // held_action.approve is explicitly idempotent by design too (ADR-001
      // Decision #5: double-approval returns the cached outcome).
      await callOperation(operation, { id: heldAction.id }, newIdempotencyKey());
      onResolved();
    } catch (err) {
      setBusy(false);
      setError(err instanceof ApiError ? err.envelope.message : String(err));
    }
  }

  return (
    <div
      className="confirm-backdrop"
      onKeyDown={(e) => {
        if (e.key === "Escape") void resolve("held_action.cancel");
      }}
    >
      <div
        className="confirm-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-label="Confirm consequential action"
      >
        <p className="confirm-dialog__label">What will happen</p>
        <p className="confirm-dialog__what">{heldAction.action}</p>

        <p className="confirm-dialog__meta">
          {heldAction.principal} · correlation {heldAction.correlation_id}
        </p>

        <p className="confirm-dialog__label">Why</p>
        <p className="confirm-dialog__why">{heldAction.reason}</p>

        <p className="confirm-dialog__reversibility">{heldAction.reversibility}</p>

        {error && <p className="confirm-dialog__error">{error}</p>}

        <div className="confirm-dialog__actions">
          <button
            ref={denyRef}
            type="button"
            className="confirm-dialog__deny"
            disabled={busy}
            onClick={() => void resolve("held_action.cancel")}
          >
            Deny
          </button>
          <button
            type="button"
            className="confirm-dialog__approve"
            disabled={busy}
            onClick={() => void resolve("held_action.approve")}
          >
            Approve
          </button>
        </div>
      </div>
    </div>
  );
}
