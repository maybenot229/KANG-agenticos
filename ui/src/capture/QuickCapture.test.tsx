import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import QuickCapture from "./QuickCapture";
import { callOperation } from "../api/client";

// ADR-012: the first of the three DOM-interaction gaps the 2026-08-05
// handoff named by name ("quick capture's DOM layer... has no automated
// UI-interaction test yet"). Mocks `callOperation` at the module boundary
// (`api/client.ts`) — the one seam every screen this session built
// already calls through, per 12_API §1; no new seam invented for
// testability.
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>(
    "../api/client",
  );
  return {
    ...actual,
    callOperation: vi.fn(),
  };
});

describe("QuickCapture", () => {
  beforeEach(() => {
    vi.mocked(callOperation).mockReset();
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("submits the typed title via task.create on Enter", async () => {
    vi.mocked(callOperation).mockResolvedValue({
      task_id: "task-1",
      revision: 1,
    });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const onClose = vi.fn();
    render(<QuickCapture onClose={onClose} />);

    const input = screen.getByPlaceholderText("Capture a task…");
    await user.type(input, "Write the M6 handoff{Enter}");

    await waitFor(() => {
      expect(callOperation).toHaveBeenCalledWith(
        "task.create",
        { title: "Write the M6 handoff" },
        expect.any(String), // a fresh idempotency key, not asserting its exact value
      );
    });
  });

  it("shows a confirmation and closes itself shortly after a successful submit", async () => {
    vi.mocked(callOperation).mockResolvedValue({
      task_id: "task-1",
      revision: 1,
    });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const onClose = vi.fn();
    render(<QuickCapture onClose={onClose} />);

    await user.type(screen.getByPlaceholderText("Capture a task…"), "x{Enter}");
    await waitFor(() => {
      expect(screen.getByText(/Captured in/)).toBeInTheDocument();
    });

    expect(onClose).not.toHaveBeenCalled(); // not before the brief-confirmation delay
    vi.advanceTimersByTime(600);
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it("renders the API's own error message on failure, without submitting again", async () => {
    const { ApiError } = await vi.importActual<typeof import("../api/client")>(
      "../api/client",
    );
    vi.mocked(callOperation).mockRejectedValue(
      new ApiError({
        code: "invalid_request",
        message: "task.create requires a 'title'",
        correlation_id: "corr-1",
        retryable: false,
      }),
    );
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<QuickCapture onClose={vi.fn()} />);

    await user.type(screen.getByPlaceholderText("Capture a task…"), "x{Enter}");

    await waitFor(() => {
      expect(
        screen.getByText("task.create requires a 'title'"),
      ).toBeInTheDocument();
    });
    expect(callOperation).toHaveBeenCalledTimes(1);
  });

  it("Escape closes without calling task.create", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const onClose = vi.fn();
    render(<QuickCapture onClose={onClose} />);

    await user.type(screen.getByPlaceholderText("Capture a task…"), "abandoned");
    await user.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(callOperation).not.toHaveBeenCalled();
  });
});
