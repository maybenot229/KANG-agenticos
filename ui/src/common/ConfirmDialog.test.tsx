import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ConfirmDialog from "./ConfirmDialog";
import { callOperation } from "../api/client";
import type { HeldActionListItem } from "../generated/held_action";

// ADR-012: the second of the three named gaps — "the confirm dialog's
// keyboard-focus/Escape behavior has no automated UI-interaction test
// yet" (2026-08-05 handoff). This dialog is 09_UI §7's "most safety-
// critical UI"; these are exactly the invariants that section names,
// each pinned so a future edit can't silently regress one.
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>(
    "../api/client",
  );
  return {
    ...actual,
    callOperation: vi.fn(),
  };
});

const HELD_ACTION: HeldActionListItem = {
  id: "held-1",
  operation: "deadline.create",
  action: "Track a deadline: Submit KANG demo video",
  principal: "kang",
  reason: "Kang asked to track this deadline.",
  reversibility: "reversible: cancel at any time before it fires",
  correlation_id: "corr-1",
  created_at: "2026-08-05T00:00:00+00:00",
  expires_at: "2026-08-12T00:00:00+00:00",
  status: "pending",
};

describe("ConfirmDialog", () => {
  beforeEach(() => {
    vi.mocked(callOperation).mockReset();
  });

  it("focuses Deny on mount, never Approve — no Enter-through to the consequential action", async () => {
    render(<ConfirmDialog heldAction={HELD_ACTION} onResolved={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Deny" })).toHaveFocus();
    });
  });

  it("Escape denies immediately, without asking why", async () => {
    vi.mocked(callOperation).mockResolvedValue({ id: "held-1", status: "cancelled" });
    const onResolved = vi.fn();
    const user = userEvent.setup();
    render(<ConfirmDialog heldAction={HELD_ACTION} onResolved={onResolved} />);

    await user.keyboard("{Escape}");

    await waitFor(() => {
      expect(callOperation).toHaveBeenCalledWith(
        "held_action.cancel",
        { id: "held-1" },
        expect.any(String),
      );
    });
    await waitFor(() => expect(onResolved).toHaveBeenCalledTimes(1));
    // No confirmation prompt of any kind rendered before resolving.
    expect(screen.queryByText(/are you sure/i)).not.toBeInTheDocument();
  });

  it("renders exactly one held action's what/who/why/reversibility, verbatim", () => {
    render(<ConfirmDialog heldAction={HELD_ACTION} onResolved={vi.fn()} />);
    expect(screen.getByText(HELD_ACTION.action)).toBeInTheDocument();
    expect(screen.getByText(HELD_ACTION.reason)).toBeInTheDocument();
    expect(screen.getByText(HELD_ACTION.reversibility)).toBeInTheDocument();
    expect(
      screen.getByText(`${HELD_ACTION.principal} · correlation ${HELD_ACTION.correlation_id}`),
    ).toBeInTheDocument();
  });

  it("clicking Approve calls held_action.approve with a fresh idempotency key", async () => {
    vi.mocked(callOperation).mockResolvedValue({ id: "held-1", status: "approved" });
    const onResolved = vi.fn();
    const user = userEvent.setup();
    render(<ConfirmDialog heldAction={HELD_ACTION} onResolved={onResolved} />);

    await user.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => {
      expect(callOperation).toHaveBeenCalledWith(
        "held_action.approve",
        { id: "held-1" },
        expect.any(String),
      );
    });
    await waitFor(() => expect(onResolved).toHaveBeenCalledTimes(1));
  });
});
