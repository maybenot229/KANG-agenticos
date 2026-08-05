import { useState } from "react";
import "./App.css";
import TodaysQuests from "./zones/TodaysQuests";
import Attention from "./zones/Attention";
import WhatChanged from "./zones/WhatChanged";
import Opportunities from "./zones/Opportunities";
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
 *
 * All four dashboard zones (09_UI §4) now render — fixed, stable
 * positions (UI-P5), Zone 1 largest and first in focus order (DOM order
 * here doubles as focus order). Zone 2 has one real data source
 * (deadline.list) and two honest gaps (competitions, approval queue);
 * Zones 3 and 4 have no backend yet at all and say so plainly rather
 * than fabricating content (09_UI §4's honest-empty-states rule). The
 * six non-Dashboard domains are still chrome-only buttons, a later slice.
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
        <div className="dashboard">
          <div className="dashboard__zone-1">
            <TodaysQuests />
          </div>
          <div className="dashboard__zone-2">
            <Attention />
          </div>
          <div className="dashboard__zone-3">
            <WhatChanged />
          </div>
          <div className="dashboard__zone-4">
            <Opportunities />
          </div>
        </div>
      </main>

      <footer className="status-strip">
        <span>No background tasks.</span>
      </footer>
    </div>
  );
}
