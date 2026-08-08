import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import InvocationsPanel from "./InvocationsPanel";
import { callOperation } from "../api/client";
import type { InvocationListItem } from "../generated/invocation";

// ADR-012's own stated floor, not ceiling: coverage extended here to
// InvocationsPanel — the row-expand-to-explain interaction (09_UI §12's
// "each row opens `kang explain`") had no automated test yet.
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>(
    "../api/client",
  );
  return {
    ...actual,
    callOperation: vi.fn(),
  };
});

const INVOCATION: InvocationListItem = {
  id: "inv-1",
  correlation_id: "corr-1",
  kind: "command",
  operation: "task.create",
  principal: "kang",
  trigger: "cli",
  started: "2026-01-01T00:00:00.000Z",
  finished: "2026-01-01T00:00:01.000Z",
  outcome: "ok",
};

function mockListThenExplain(explainResult: unknown) {
  vi.mocked(callOperation).mockImplementation((operation: string) => {
    if (operation === "invocation.list") {
      return Promise.resolve({ invocations: [INVOCATION] });
    }
    if (operation === "explain.invocation") {
      return Promise.resolve(explainResult);
    }
    return Promise.reject(new Error(`unexpected operation ${operation}`));
  });
}

describe("InvocationsPanel", () => {
  beforeEach(() => {
    vi.mocked(callOperation).mockReset();
  });

  it("shows the empty state when nothing has been invoked yet", async () => {
    vi.mocked(callOperation).mockResolvedValue({ invocations: [] });
    render(<InvocationsPanel />);
    await waitFor(() => {
      expect(screen.getByText("No invocations recorded yet.")).toBeInTheDocument();
    });
  });

  it("renders a row with its outcome, operation, and computed duration", async () => {
    mockListThenExplain(null);
    render(<InvocationsPanel />);
    await waitFor(() => {
      expect(screen.getByText("task.create")).toBeInTheDocument();
    });
    expect(screen.getByText("ok")).toBeInTheDocument();
    expect(screen.getByText(/1\.0s/)).toBeInTheDocument();
  });

  it("shows 'running…' for an invocation with no finished timestamp yet", async () => {
    vi.mocked(callOperation).mockResolvedValue({
      invocations: [{ ...INVOCATION, finished: null, outcome: null }],
    });
    render(<InvocationsPanel />);
    await waitFor(() => {
      expect(screen.getByText(/running…/)).toBeInTheDocument();
    });
    expect(screen.getByText("pending")).toBeInTheDocument();
  });

  it("clicking a row calls explain.invocation and renders the reconstruction", async () => {
    mockListThenExplain({
      correlation_id: "corr-1",
      trigger: "cli",
      operation: "task.create",
      principal: "kang",
      kind: "command",
      manifest: null,
      started: INVOCATION.started,
      finished: INVOCATION.finished,
      outcome: "ok",
      chain: [
        { action: "task.create.dispatched", principal: "kang", at: "t1", details: null },
        { action: "task.create.ok", principal: "kang", at: "t2", details: null },
      ],
      reconstructed_from: "invocation + audit (permanent storage)",
    });
    const user = userEvent.setup();
    render(<InvocationsPanel />);
    await waitFor(() => screen.getByText("task.create"));

    await user.click(screen.getByRole("button", { expanded: false }));

    await waitFor(() => {
      expect(
        screen.getByText(/Reconstructed from invocation \+ audit/),
      ).toBeInTheDocument();
    });
    expect(callOperation).toHaveBeenCalledWith("explain.invocation", {
      correlation_id: "corr-1",
    });
    expect(screen.getByText(/task.create.dispatched/)).toBeInTheDocument();
    expect(screen.getByText(/task.create.ok/)).toBeInTheDocument();
  });

  it("clicking an expanded row again collapses it without a second fetch", async () => {
    mockListThenExplain({
      correlation_id: "corr-1",
      trigger: "cli",
      operation: "task.create",
      principal: "kang",
      kind: "command",
      manifest: null,
      started: INVOCATION.started,
      finished: INVOCATION.finished,
      outcome: "ok",
      chain: [],
      reconstructed_from: "invocation + audit (permanent storage)",
    });
    const user = userEvent.setup();
    render(<InvocationsPanel />);
    await waitFor(() => screen.getByText("task.create"));

    const row = screen.getByRole("button", { expanded: false });
    await user.click(row);
    await waitFor(() => screen.getByText(/Reconstructed from/));

    await user.click(screen.getByRole("button", { expanded: true }));
    expect(screen.queryByText(/Reconstructed from/)).not.toBeInTheDocument();
    // list + one explain call only — collapsing does not re-fetch
    expect(
      vi.mocked(callOperation).mock.calls.filter((c) => c[0] === "explain.invocation"),
    ).toHaveLength(1);
  });

  it("renders the API's own error message when the list call fails", async () => {
    const { ApiError } = await vi.importActual<typeof import("../api/client")>(
      "../api/client",
    );
    vi.mocked(callOperation).mockRejectedValue(
      new ApiError({
        code: "internal",
        message: "something failed",
        correlation_id: "corr-1",
        retryable: false,
      }),
    );
    render(<InvocationsPanel />);
    await waitFor(() => {
      expect(screen.getByText("something failed")).toBeInTheDocument();
    });
  });
});
