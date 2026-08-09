import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ProjectsScreen from "./ProjectsScreen";
import { callOperation } from "../api/client";

// The one named gap left from ADR-015's own session (2026-08-07):
// "ProjectsScreen's click-through to ProjectDetail has no dedicated UI
// test" — every other interactive surface added that session got
// Vitest coverage; this was the last thing built, and got missed.
// Closed here, 2026-08-09.
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>(
    "../api/client",
  );
  return {
    ...actual,
    callOperation: vi.fn(),
  };
});

const PROJECT = {
  id: "proj-1",
  name: "KANG v0.1",
  status: "active",
  description: "Ship the agentic OS",
  vault_folder: null,
  github_repo: "maybenot229/KANG",
  goal_id: null,
};

const PENDING_MILESTONE = {
  id: "ms-1",
  project_id: "proj-1",
  title: "First real milestone",
  status: "pending",
  due: null,
};

function mockListThenMilestones(milestones: unknown[] = []) {
  vi.mocked(callOperation).mockImplementation((operation: string) => {
    if (operation === "project.list") {
      return Promise.resolve({ projects: [PROJECT] });
    }
    if (operation === "milestone.list") {
      return Promise.resolve({ milestones });
    }
    return Promise.reject(new Error(`unexpected operation ${operation}`));
  });
}

async function openDetail(user: ReturnType<typeof userEvent.setup>) {
  await waitFor(() => screen.getByText("KANG v0.1"));
  await user.click(screen.getByRole("button", { name: /KANG v0\.1/ }));
  await waitFor(() => screen.getByRole("heading", { name: "KANG v0.1" }));
}

describe("ProjectsScreen", () => {
  beforeEach(() => {
    vi.mocked(callOperation).mockReset();
  });

  it("renders the tracked project list", async () => {
    mockListThenMilestones();
    render(<ProjectsScreen formOpen={false} onFormOpenChange={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByText("KANG v0.1")).toBeInTheDocument();
    });
    expect(screen.getByText(/maybenot229\/KANG/)).toBeInTheDocument();
  });

  it("clicking a project opens its detail view, fetching that project's milestones", async () => {
    const user = userEvent.setup();
    mockListThenMilestones();
    render(<ProjectsScreen formOpen={false} onFormOpenChange={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("KANG v0.1")).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: /KANG v0\.1/ }));

    // Depth 2: the detail view, not the list, is now on screen.
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "KANG v0.1" }),
      ).toBeInTheDocument();
    });
    expect(callOperation).toHaveBeenCalledWith("milestone.list", {
      project_id: "proj-1",
    });
    expect(screen.getByText("No milestones tracked yet.")).toBeInTheDocument();
  });

  it("the detail view's back button returns to the project list", async () => {
    const user = userEvent.setup();
    mockListThenMilestones();
    render(<ProjectsScreen formOpen={false} onFormOpenChange={vi.fn()} />);

    await waitFor(() => screen.getByText("KANG v0.1"));
    await user.click(screen.getByRole("button", { name: /KANG v0\.1/ }));
    await waitFor(() =>
      screen.getByRole("heading", { name: "KANG v0.1" }),
    );

    await user.click(screen.getByRole("button", { name: "← Projects" }));

    // Back on the list — its own heading is visible again, the
    // detail-only "Milestones" subheading is gone.
    expect(
      screen.getByRole("heading", { name: /Projects/ }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Milestones")).not.toBeInTheDocument();
  });

  it("a pending milestone offers Reach/Miss/Drop; Reach calls milestone.reach with a fresh idempotency key", async () => {
    const user = userEvent.setup();
    mockListThenMilestones([PENDING_MILESTONE]);
    render(<ProjectsScreen formOpen={false} onFormOpenChange={vi.fn()} />);
    await openDetail(user);

    await waitFor(() => {
      expect(screen.getByText("First real milestone")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Reach" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Miss" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Drop" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Reach" }));

    await waitFor(() => {
      expect(callOperation).toHaveBeenCalledWith(
        "milestone.reach",
        { id: "ms-1" },
        expect.any(String),
      );
    });
  });

  it("a reached milestone offers no transition buttons", async () => {
    const user = userEvent.setup();
    mockListThenMilestones([{ ...PENDING_MILESTONE, status: "reached" }]);
    render(<ProjectsScreen formOpen={false} onFormOpenChange={vi.fn()} />);
    await openDetail(user);

    await waitFor(() => screen.getByText("First real milestone"));
    expect(screen.queryByRole("button", { name: "Reach" })).not.toBeInTheDocument();
  });

  it("an active project offers Complete; clicking it calls project.complete then returns to a re-fetched list", async () => {
    const user = userEvent.setup();
    let listCallCount = 0;
    vi.mocked(callOperation).mockImplementation((operation: string) => {
      if (operation === "project.list") {
        listCallCount += 1;
        return Promise.resolve({
          projects: [
            listCallCount === 1 ? PROJECT : { ...PROJECT, status: "completed" },
          ],
        });
      }
      if (operation === "milestone.list") {
        return Promise.resolve({ milestones: [] });
      }
      if (operation === "project.complete") {
        return Promise.resolve({ project_id: "proj-1", revision: 2 });
      }
      return Promise.reject(new Error(`unexpected operation ${operation}`));
    });
    render(<ProjectsScreen formOpen={false} onFormOpenChange={vi.fn()} />);
    await openDetail(user);

    const completeButton = screen.getByRole("button", { name: "Complete" });
    await user.click(completeButton);

    await waitFor(() => {
      expect(callOperation).toHaveBeenCalledWith(
        "project.complete",
        { id: "proj-1" },
        expect.any(String),
      );
    });
    // Closes the detail view and reflects the re-fetched (now completed) list.
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: /Projects/ }),
      ).toBeInTheDocument();
    });
    expect(screen.getByText(/completed/)).toBeInTheDocument();
  });
});
