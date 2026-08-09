import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import TodaysQuests from "./TodaysQuests";
import { callOperation } from "../api/client";

// task.complete's UI entry point (added 2026-08-09) — Zone 1's "Done"
// button, the first place completing anything is possible in the app.
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>(
    "../api/client",
  );
  return {
    ...actual,
    callOperation: vi.fn(),
  };
});

const PLAN_WITH_ONE_QUEST = {
  plan_date: "2026-08-09",
  quest_ids: ["task-1"],
  deadline_ids: [],
  calendar_event_ids: [],
  estimated_minutes: 30,
  deferred_count: 0,
};

const QUEST_TASK = {
  id: "task-1",
  title: "Ship the goal domain",
  status: "open",
  priority: 2,
  revision: 1,
};

const EMPTY_PLAN = { ...PLAN_WITH_ONE_QUEST, quest_ids: [] };

describe("TodaysQuests", () => {
  beforeEach(() => {
    vi.mocked(callOperation).mockReset();
  });

  it("renders a Done button per quest", async () => {
    vi.mocked(callOperation).mockImplementation(async (op: string) => {
      if (op === "plan.generate") return PLAN_WITH_ONE_QUEST;
      if (op === "task.get") return QUEST_TASK;
      throw new Error(`unexpected op ${op}`);
    });
    render(<TodaysQuests />);

    await waitFor(() => {
      expect(screen.getByText("Ship the goal domain")).toBeInTheDocument();
    });
    expect(
      screen.getByRole("button", { name: 'Mark "Ship the goal domain" done' }),
    ).toBeInTheDocument();
  });

  it("clicking Done calls task.complete with a fresh idempotency key, then re-fetches", async () => {
    const user = userEvent.setup();
    let planCallCount = 0;
    vi.mocked(callOperation).mockImplementation(
      async (op: string, params?: unknown) => {
        if (op === "plan.generate") {
          planCallCount += 1;
          return planCallCount === 1 ? PLAN_WITH_ONE_QUEST : EMPTY_PLAN;
        }
        if (op === "task.get") return QUEST_TASK;
        if (op === "task.complete") {
          return { task_id: "task-1", revision: 2, completed_at: "2026-08-09T00:00:00Z" };
        }
        throw new Error(`unexpected op ${op} ${JSON.stringify(params)}`);
      },
    );
    render(<TodaysQuests />);

    await waitFor(() => {
      expect(screen.getByText("Ship the goal domain")).toBeInTheDocument();
    });
    await user.click(
      screen.getByRole("button", { name: 'Mark "Ship the goal domain" done' }),
    );

    await waitFor(() => {
      expect(callOperation).toHaveBeenCalledWith(
        "task.complete",
        { id: "task-1" },
        expect.any(String),
      );
    });
    // The completed quest no longer matches plannable() — re-fetch reflects that.
    await waitFor(() => {
      expect(screen.getByText("No quests scheduled today.")).toBeInTheDocument();
    });
  });
});
