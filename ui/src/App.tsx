import { useState } from "react";
import "./App.css";
import TodaysQuests from "./zones/TodaysQuests";
import QuickCapture from "./capture/QuickCapture";

// The seven domains (UI-001, 09_UI_DESIGN.md §2): fixed order, MUST NOT
// reorder or hide contextually (UI-P5). Dashboard is the hub, not a
// domain — reachable separately, always first.
const DOMAINS = [
  "Plan",
  "Projects",
  "Competitions",
  "Learn",
  "Know",
  "System",
  "Chat",
] as const;

/**
 * The persistent chrome (09_UI §3): identical on every screen. This
 * component owns layout only — no truth, no domain logic (UI-P1).
 * Zone 1 (Today's Quests) and quick capture are the vertical slice this
 * session proves against real data; the remaining three zones and the
 * other six domains are later slices.
 */
export default function App() {
  const [captureOpen, setCaptureOpen] = useState(false);

  return (
    <div className="shell">
      <header className="top-bar">
        <span className="top-bar__breadcrumb">Dashboard</span>
        <span className="top-bar__palette-hint">⌘K</span>
      </header>

      <nav className="left-rail" aria-label="Domains">
        <ul>
          {DOMAINS.map((domain) => (
            <li key={domain}>
              <button type="button" className="left-rail__item">
                {domain}
              </button>
            </li>
          ))}
        </ul>
        <button
          type="button"
          className="left-rail__capture"
          onClick={() => setCaptureOpen((open) => !open)}
        >
          + Quick capture
        </button>
        {captureOpen && <QuickCapture onClose={() => setCaptureOpen(false)} />}
      </nav>

      <main className="content-area">
        <TodaysQuests />
      </main>

      <footer className="status-strip">
        <span>No background tasks.</span>
      </footer>
    </div>
  );
}
