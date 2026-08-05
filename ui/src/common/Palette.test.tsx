import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Palette from "./Palette";

// ADR-012: the third of the three named gaps — "the palette's Ctrl+K/
// Escape/Enter/arrow-key behavior has no automated UI-interaction test
// yet" (2026-08-05 handoff). Ctrl+K itself is a window-level listener in
// App.tsx (out of scope here — see the ADR's Consequences on scope);
// this covers the palette's own internal keyboard contract once open,
// per Decision UI-002.

const LOCATIONS = ["Dashboard", "Plan", "Projects", "System"] as const;

function renderPalette(overrides: Partial<Parameters<typeof Palette>[0]> = {}) {
  const onNavigate = vi.fn();
  const onOpenCapture = vi.fn();
  const onOpenDeadlineForm = vi.fn();
  const onClose = vi.fn();
  render(
    <Palette
      locations={LOCATIONS}
      currentLocation="Dashboard"
      onNavigate={onNavigate}
      onOpenCapture={onOpenCapture}
      onOpenDeadlineForm={onOpenDeadlineForm}
      onClose={onClose}
      {...overrides}
    />,
  );
  return { onNavigate, onOpenCapture, onOpenDeadlineForm, onClose };
}

describe("Palette", () => {
  it("focuses its input on mount (Ctrl+K -> type immediately, no extra click)", () => {
    renderPalette();
    expect(screen.getByPlaceholderText("Navigate, act, or find…")).toHaveFocus();
  });

  it("Escape closes the palette", async () => {
    const user = userEvent.setup();
    const { onClose } = renderPalette();
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("filters the Navigate register by the typed query", async () => {
    const user = userEvent.setup();
    renderPalette();
    await user.keyboard("plan");
    expect(screen.getByRole("button", { name: "Plan" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "System" })).not.toBeInTheDocument();
  });

  it("Enter on the first result navigates there and closes", async () => {
    const user = userEvent.setup();
    const { onNavigate, onClose } = renderPalette();
    await user.keyboard("plan{Enter}");
    expect(onNavigate).toHaveBeenCalledWith("Plan");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("ArrowDown moves selection before Enter runs it", async () => {
    const user = userEvent.setup();
    const { onNavigate } = renderPalette();
    // Unfiltered: Dashboard, Plan, Projects, System — ArrowDown once lands
    // on the second (Plan), not the first (Dashboard, the default).
    await user.keyboard("{ArrowDown}{Enter}");
    expect(onNavigate).toHaveBeenCalledWith("Plan");
  });

  it('"New task…" runs the Act register\'s quick-capture command', async () => {
    const user = userEvent.setup();
    const { onOpenCapture, onClose } = renderPalette();
    await user.keyboard("new task{Enter}");
    expect(onOpenCapture).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('"New deadline…" runs the Act register\'s deadline-form command', async () => {
    const user = userEvent.setup();
    const { onOpenDeadlineForm, onClose } = renderPalette();
    await user.keyboard("new deadline{Enter}");
    expect(onOpenDeadlineForm).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("shows the Find register's honest not-built-yet note, never fabricated results", async () => {
    renderPalette();
    expect(
      screen.getByText(/Memory\/vault search isn't available yet/),
    ).toBeInTheDocument();
  });
});
