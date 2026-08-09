import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PlanScreen from "./PlanScreen";
import { callOperation } from "../api/client";

// goal.achieve/.revise/.retire (ADR-018, added 2026-08-10) — the Goals
// section's first status-transition UI, mirroring TodaysQuests' "Done"
// button and ProjectDetail's milestone actions.
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>(
    "../api/client",
  );
  return {
    ...actual,
    callOperation: vi.fn(),
  };
});

const EMPTY_PLAN = {
  plan_date: "2026-08-10",
  quest_ids: [],
  deadline_ids: [],
  calendar_event_ids: [],
  estimated_minutes: 0,
  deferred_count: 0,
};

const ACTIVE_GOAL = {
  id: "goal-1",
  title: "Ship KANG v0.1",
  horizon: "quarter",
  status: "active",
  description: null,
};

function mockPlanThenGoals(goals: unknown[] = []) {
  vi.mocked(callOperation).mockImplementation((operation: string) => {
    if (operation === "plan.generate") return Promise.resolve(EMPTY_PLAN);
    if (operation === "deadline.list") return Promise.resolve({ deadlines: [] });
    if (operation === "goal.list") return Promise.resolve({ goals });
    return Promise.reject(new Error(`unexpected operation ${operation}`));
  });
}

describe("PlanScreen — Goals", () => {
  beforeEach(() => {
    vi.mocked(callOperation).mockReset();
  });

  it("an active goal offers Achieve/Revise/Retire", async () => {
    mockPlanThenGoals([ACTIVE_GOAL]);
    render(<PlanScreen goalFormOpen={false} onGoalFormOpenChange={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByText("Ship KANG v0.1")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Achieve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Revise" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retire" })).toBeInTheDocument();
  });

  it("clicking Achieve calls goal.achieve with a fresh idempotency key, then re-fetches", async () => {
    const user = userEvent.setup();
    let listCallCount = 0;
    vi.mocked(callOperation).mockImplementation((operation: string) => {
      if (operation === "plan.generate") return Promise.resolve(EMPTY_PLAN);
      if (operation === "deadline.list") return Promise.resolve({ deadlines: [] });
      if (operation === "goal.list") {
        listCallCount += 1;
        return Promise.resolve({
          goals: listCallCount === 1 ? [ACTIVE_GOAL] : [],
        });
      }
      if (operation === "goal.achieve") {
        return Promise.resolve({ goal_id: "goal-1", revision: 2 });
      }
      return Promise.reject(new Error(`unexpected operation ${operation}`));
    });
    render(<PlanScreen goalFormOpen={false} onGoalFormOpenChange={vi.fn()} />);

    await waitFor(() => screen.getByText("Ship KANG v0.1"));
    await user.click(screen.getByRole("button", { name: "Achieve" }));

    await waitFor(() => {
      expect(callOperation).toHaveBeenCalledWith(
        "goal.achieve",
        { id: "goal-1" },
        expect.any(String),
      );
    });
    // The now-achieved goal drops off the re-fetched active-only display.
    await waitFor(() => {
      expect(screen.queryByText("Ship KANG v0.1")).not.toBeInTheDocument();
    });
  });

  it("a retired goal offers no transition buttons", async () => {
    mockPlanThenGoals([{ ...ACTIVE_GOAL, status: "retired" }]);
    render(<PlanScreen goalFormOpen={false} onGoalFormOpenChange={vi.fn()} />);
    await waitFor(() => screen.getByText("Ship KANG v0.1"));
    expect(screen.queryByRole("button", { name: "Achieve" })).not.toBeInTheDocument();
  });
});
