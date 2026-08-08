import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ProjectForm from "./ProjectForm";
import { callOperation } from "../api/client";

// ADR-012's own stated floor, not ceiling: coverage extended here to
// ProjectForm — ADR-013's project-tracking form had no automated test.
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>(
    "../api/client",
  );
  return {
    ...actual,
    callOperation: vi.fn(),
  };
});

describe("ProjectForm", () => {
  beforeEach(() => {
    vi.mocked(callOperation).mockReset();
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("Track is disabled until a name is entered", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<ProjectForm onClose={vi.fn()} />);

    const track = screen.getByRole("button", { name: "Track" });
    expect(track).toBeDisabled();

    await user.type(screen.getByPlaceholderText("Project name…"), "KANG v0.1");
    expect(track).toBeEnabled();
  });

  it("submits name plus optional fields, nulling blank ones, with a fresh idempotency key", async () => {
    vi.mocked(callOperation).mockResolvedValue({
      project_id: "proj-1",
      revision: 1,
    });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<ProjectForm onClose={vi.fn()} />);

    await user.type(screen.getByPlaceholderText("Project name…"), "KANG v0.1");
    await user.type(
      screen.getByPlaceholderText("Description (optional)…"),
      "Ship the agentic OS",
    );
    // github repo left blank
    await user.click(screen.getByRole("button", { name: "Track" }));

    await waitFor(() => {
      expect(callOperation).toHaveBeenCalledWith(
        "project.create",
        {
          name: "KANG v0.1",
          description: "Ship the agentic OS",
          github_repo: null,
        },
        expect.any(String),
      );
    });
  });

  it("shows 'Tracked.' and closes itself shortly after a successful submit", async () => {
    vi.mocked(callOperation).mockResolvedValue({
      project_id: "proj-1",
      revision: 1,
    });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const onClose = vi.fn();
    render(<ProjectForm onClose={onClose} />);

    await user.type(screen.getByPlaceholderText("Project name…"), "x");
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
    render(<ProjectForm onClose={vi.fn()} />);

    await user.type(screen.getByPlaceholderText("Project name…"), "x");
    await user.click(screen.getByRole("button", { name: "Track" }));

    await waitFor(() => {
      expect(screen.getByText("name must be non-empty")).toBeInTheDocument();
    });
  });

  it("Escape on the name field closes without submitting", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const onClose = vi.fn();
    render(<ProjectForm onClose={onClose} />);

    await user.type(screen.getByPlaceholderText("Project name…"), "abandoned");
    await user.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(callOperation).not.toHaveBeenCalled();
  });

  it("Cancel closes immediately without submitting", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const onClose = vi.fn();
    render(<ProjectForm onClose={onClose} />);

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(callOperation).not.toHaveBeenCalled();
  });
});
