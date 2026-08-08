import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DeadlineForm from "./DeadlineForm";
import { callOperation } from "../api/client";

// ADR-012's own stated floor, not ceiling: coverage extended here to
// DeadlineForm — 09_UI §4's deadline-tracking form had no automated test.
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>(
    "../api/client",
  );
  return {
    ...actual,
    callOperation: vi.fn(),
  };
});

describe("DeadlineForm", () => {
  beforeEach(() => {
    vi.mocked(callOperation).mockReset();
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("Track is disabled until both a title and a due date are entered", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<DeadlineForm onClose={vi.fn()} />);

    const track = screen.getByRole("button", { name: "Track" });
    expect(track).toBeDisabled();

    await user.type(screen.getByPlaceholderText("Deadline title…"), "Submit entry");
    expect(track).toBeDisabled(); // title alone isn't enough

    const at = screen.getByLabelText("Due at");
    await user.type(at, "2026-09-01T17:00");
    expect(track).toBeEnabled();
  });

  it("defaults kind to custom and submits with a fresh idempotency key", async () => {
    vi.mocked(callOperation).mockResolvedValue({
      deadline_id: "dl-1",
      revision: 1,
    });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<DeadlineForm onClose={vi.fn()} />);

    await user.type(screen.getByPlaceholderText("Deadline title…"), "Submit entry");
    await user.type(screen.getByLabelText("Due at"), "2026-09-01T17:00");
    await user.click(screen.getByRole("button", { name: "Track" }));

    await waitFor(() => {
      expect(callOperation).toHaveBeenCalledWith(
        "deadline.create",
        { title: "Submit entry", at: "2026-09-01T17:00", kind: "custom" },
        expect.any(String),
      );
    });
  });

  it("only offers the self-standing kinds (custom, school)", () => {
    render(<DeadlineForm onClose={vi.fn()} />);
    const select = screen.getByLabelText("Kind") as HTMLSelectElement;
    const values = Array.from(select.querySelectorAll("option")).map((o) => o.value);
    expect(values).toEqual(["custom", "school"]);
  });

  it("shows 'Tracked.' and closes itself shortly after a successful submit", async () => {
    vi.mocked(callOperation).mockResolvedValue({
      deadline_id: "dl-1",
      revision: 1,
    });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const onClose = vi.fn();
    render(<DeadlineForm onClose={onClose} />);

    await user.type(screen.getByPlaceholderText("Deadline title…"), "x");
    await user.type(screen.getByLabelText("Due at"), "2026-09-01T17:00");
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
        message: "deadline `at` must be ISO-8601",
        correlation_id: "corr-1",
        retryable: false,
      }),
    );
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<DeadlineForm onClose={vi.fn()} />);

    await user.type(screen.getByPlaceholderText("Deadline title…"), "x");
    await user.type(screen.getByLabelText("Due at"), "2026-09-01T17:00");
    await user.click(screen.getByRole("button", { name: "Track" }));

    await waitFor(() => {
      expect(
        screen.getByText("deadline `at` must be ISO-8601"),
      ).toBeInTheDocument();
    });
  });

  it("Escape on the title field closes without submitting", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const onClose = vi.fn();
    render(<DeadlineForm onClose={onClose} />);

    await user.type(screen.getByPlaceholderText("Deadline title…"), "abandoned");
    await user.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(callOperation).not.toHaveBeenCalled();
  });

  it("Cancel closes immediately without submitting", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const onClose = vi.fn();
    render(<DeadlineForm onClose={onClose} />);

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(callOperation).not.toHaveBeenCalled();
  });
});
