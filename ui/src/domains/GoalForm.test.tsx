import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import GoalForm from "./GoalForm";
import { callOperation } from "../api/client";

// ADR-016's UI: goal.create's tracking form, mirroring ProjectForm.test.tsx's
// own coverage exactly, with horizon (required select) added.
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>(
    "../api/client",
  );
  return {
    ...actual,
    callOperation: vi.fn(),
  };
});

describe("GoalForm", () => {
  beforeEach(() => {
    vi.mocked(callOperation).mockReset();
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("Track is disabled until a title is entered", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<GoalForm onClose={vi.fn()} />);

    const track = screen.getByRole("button", { name: "Track" });
    expect(track).toBeDisabled();

    await user.type(screen.getByPlaceholderText("Goal title…"), "Ship KANG v0.1");
    expect(track).toBeEnabled();
  });

  it("horizon defaults to quarter and submits with the selected value", async () => {
    vi.mocked(callOperation).mockResolvedValue({ goal_id: "goal-1", revision: 1 });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<GoalForm onClose={vi.fn()} />);

    expect(screen.getByRole("combobox", { name: "Horizon" })).toHaveValue("quarter");

    await user.type(screen.getByPlaceholderText("Goal title…"), "Ranked year goal");
    await user.selectOptions(screen.getByRole("combobox", { name: "Horizon" }), "year");
    await user.click(screen.getByRole("button", { name: "Track" }));

    await waitFor(() => {
      expect(callOperation).toHaveBeenCalledWith(
        "goal.create",
        {
          title: "Ranked year goal",
          horizon: "year",
          description: null,
        },
        expect.any(String),
      );
    });
  });

  it("shows 'Tracked.' and closes itself shortly after a successful submit", async () => {
    vi.mocked(callOperation).mockResolvedValue({ goal_id: "goal-1", revision: 1 });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const onClose = vi.fn();
    render(<GoalForm onClose={onClose} />);

    await user.type(screen.getByPlaceholderText("Goal title…"), "x");
    await user.click(screen.getByRole("button", { name: "Track" }));

    await waitFor(() => expect(screen.getByText("Tracked.")).toBeInTheDocument());
    expect(onClose).not.toHaveBeenCalled();
    vi.advanceTimersByTime(600);
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it("renders the API's own error message on failure", async () => {
    const { ApiError } = await vi.importActual<typeof import("../api/client")>(
      "../api/client",
    );
    vi.mocked(callOperation).mockRejectedValue(
      new ApiError({
        code: "invalid_request",
        message: "title must be non-empty",
        correlation_id: "corr-1",
        retryable: false,
      }),
    );
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<GoalForm onClose={vi.fn()} />);

    await user.type(screen.getByPlaceholderText("Goal title…"), "x");
    await user.click(screen.getByRole("button", { name: "Track" }));

    await waitFor(() => {
      expect(screen.getByText("title must be non-empty")).toBeInTheDocument();
    });
  });

  it("Escape on the title field closes without submitting", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const onClose = vi.fn();
    render(<GoalForm onClose={onClose} />);

    await user.type(screen.getByPlaceholderText("Goal title…"), "abandoned");
    await user.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(callOperation).not.toHaveBeenCalled();
  });

  it("Cancel closes immediately without submitting", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const onClose = vi.fn();
    render(<GoalForm onClose={onClose} />);

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(callOperation).not.toHaveBeenCalled();
  });
});
