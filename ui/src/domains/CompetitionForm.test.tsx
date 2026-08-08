import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import CompetitionForm from "./CompetitionForm";
import { callOperation } from "../api/client";

// ADR-012's own stated floor, not ceiling: coverage extended here to
// CompetitionForm — ADR-014's competition-tracking form had no automated
// test.
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>(
    "../api/client",
  );
  return {
    ...actual,
    callOperation: vi.fn(),
  };
});

describe("CompetitionForm", () => {
  beforeEach(() => {
    vi.mocked(callOperation).mockReset();
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("Track is disabled until a name is entered", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<CompetitionForm onClose={vi.fn()} />);

    const track = screen.getByRole("button", { name: "Track" });
    expect(track).toBeDisabled();

    await user.type(screen.getByPlaceholderText("Competition name…"), "USACO");
    expect(track).toBeEnabled();
  });

  it("submits name plus url, nulling a blank url, with a fresh idempotency key", async () => {
    vi.mocked(callOperation).mockResolvedValue({
      competition_id: "comp-1",
      revision: 1,
    });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<CompetitionForm onClose={vi.fn()} />);

    await user.type(screen.getByPlaceholderText("Competition name…"), "USACO");
    await user.click(screen.getByRole("button", { name: "Track" }));

    await waitFor(() => {
      expect(callOperation).toHaveBeenCalledWith(
        "competition.create",
        { name: "USACO", url: null },
        expect.any(String),
      );
    });
  });

  it("shows 'Tracked.' and closes itself shortly after a successful submit", async () => {
    vi.mocked(callOperation).mockResolvedValue({
      competition_id: "comp-1",
      revision: 1,
    });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const onClose = vi.fn();
    render(<CompetitionForm onClose={onClose} />);

    await user.type(screen.getByPlaceholderText("Competition name…"), "x");
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
        message: "name must be non-empty",
        correlation_id: "corr-1",
        retryable: false,
      }),
    );
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<CompetitionForm onClose={vi.fn()} />);

    await user.type(screen.getByPlaceholderText("Competition name…"), "x");
    await user.click(screen.getByRole("button", { name: "Track" }));

    await waitFor(() => {
      expect(screen.getByText("name must be non-empty")).toBeInTheDocument();
    });
  });

  it("Escape on the name field closes without submitting", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const onClose = vi.fn();
    render(<CompetitionForm onClose={onClose} />);

    await user.type(screen.getByPlaceholderText("Competition name…"), "abandoned");
    await user.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(callOperation).not.toHaveBeenCalled();
  });

  it("Cancel closes immediately without submitting", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const onClose = vi.fn();
    render(<CompetitionForm onClose={onClose} />);

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(callOperation).not.toHaveBeenCalled();
  });
});
