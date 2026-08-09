import { useEffect, useState } from "react";
import "./App.css";
import TodaysQuests from "./zones/TodaysQuests";
import Attention from "./zones/Attention";
import WhatChanged from "./zones/WhatChanged";
import Opportunities from "./zones/Opportunities";
import QuickCapture from "./capture/QuickCapture";
import PlanScreen from "./domains/PlanScreen";
import ProjectsScreen from "./domains/ProjectsScreen";
import CompetitionsScreen from "./domains/CompetitionsScreen";
import LearnScreen from "./domains/LearnScreen";
import KnowScreen from "./domains/KnowScreen";
import SystemScreen from "./domains/SystemScreen";
import ChatScreen from "./domains/ChatScreen";
import Palette from "./common/Palette";

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

type Domain = (typeof DOMAINS)[number];
type Location = "Dashboard" | Domain;

// The palette's Navigate register (UI-002): every real location, in the
// same fixed order as the rail — Dashboard first (it's "reachable
// separately," not a rail button, but still a real navigate target).
const LOCATIONS: readonly Location[] = ["Dashboard", ...DOMAINS];

// One screen component per domain (UI-001's hub-and-spoke: domain ->
// entity -> detail, depth 3 max). Plan and System have a real backend
// today; the rest are honest empty screens (see each file's own
// docstring for exactly what's missing and why) — never fabricated
// content standing in for a domain that doesn't exist yet.
//
// Projects and Competitions are rendered separately below, not through
// this map (added 2026-08-09): both need `formOpen`/`onFormOpenChange`
// props so the palette's "New project…"/"New competition…" commands can
// open their forms from any location (mirroring `deadlineFormOpen`'s
// own lift for Zone 2/Dashboard) — every other domain screen here still
// takes no props at all.
const DOMAIN_SCREENS: Partial<Record<Domain, () => JSX.Element>> = {
  Plan: PlanScreen,
  Learn: LearnScreen,
  Know: KnowScreen,
  System: SystemScreen,
  Chat: ChatScreen,
};

/**
 * The persistent chrome (09_UI §3): identical on every screen. This
 * component owns layout only — no truth, no domain logic (UI-P1).
 *
 * All four dashboard zones (09_UI §4) render at the hub. Navigation is
 * now real (UI-001: hub + seven spokes) — clicking a domain button
 * switches the content area to that domain's screen; the breadcrumb
 * doubles as the way back to the hub, since Dashboard is "reachable
 * separately," not one of the seven rail buttons.
 */
export default function App() {
  const [captureOpen, setCaptureOpen] = useState(false);
  const [location, setLocation] = useState<Location>("Dashboard");
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [deadlineFormOpen, setDeadlineFormOpen] = useState(false);
  const [projectFormOpen, setProjectFormOpen] = useState(false);
  const [competitionFormOpen, setCompetitionFormOpen] = useState(false);

  // Ctrl+K opens the palette from anywhere in the app (UI-002: "open
  // from anywhere") — a window-level listener, not scoped to one
  // element, and deliberately not the OS-level global hotkey quick
  // capture owns (Ctrl+Shift+Space, ui/shell/src/main.rs): this is an
  // in-app shortcut, only live while KANG's own window has focus.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((open) => !open);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const ActiveDomainScreen =
    location === "Dashboard" ? null : DOMAIN_SCREENS[location] ?? null;

  return (
    <div className="shell">
      <header className="top-bar">
        <button
          type="button"
          className="top-bar__breadcrumb"
          onClick={() => setLocation("Dashboard")}
        >
          {location}
        </button>
        <button
          type="button"
          className="top-bar__palette-hint"
          onClick={() => setPaletteOpen(true)}
        >
          ⌘K
        </button>
      </header>

      {paletteOpen && (
        <Palette
          locations={LOCATIONS}
          currentLocation={location}
          onNavigate={(loc) => setLocation(loc as Location)}
          onOpenCapture={() => setCaptureOpen(true)}
          onOpenDeadlineForm={() => {
            setLocation("Dashboard"); // Zone 2 (where the form lives) is Dashboard-only
            setDeadlineFormOpen(true);
          }}
          onOpenProjectForm={() => {
            setLocation("Projects");
            setProjectFormOpen(true);
          }}
          onOpenCompetitionForm={() => {
            setLocation("Competitions");
            setCompetitionFormOpen(true);
          }}
          onClose={() => setPaletteOpen(false)}
        />
      )}

      <nav className="left-rail" aria-label="Domains">
        <ul>
          {DOMAINS.map((domain) => (
            <li key={domain}>
              <button
                type="button"
                className="left-rail__item"
                aria-current={location === domain ? "page" : undefined}
                onClick={() => setLocation(domain)}
              >
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
        {location === "Dashboard" ? (
          <div className="dashboard">
            <div className="dashboard__zone-1">
              <TodaysQuests />
            </div>
            <div className="dashboard__zone-2">
              <Attention
                formOpen={deadlineFormOpen}
                onFormOpenChange={setDeadlineFormOpen}
              />
            </div>
            <div className="dashboard__zone-3">
              <WhatChanged />
            </div>
            <div className="dashboard__zone-4">
              <Opportunities />
            </div>
          </div>
        ) : location === "Projects" ? (
          <ProjectsScreen
            formOpen={projectFormOpen}
            onFormOpenChange={setProjectFormOpen}
          />
        ) : location === "Competitions" ? (
          <CompetitionsScreen
            formOpen={competitionFormOpen}
            onFormOpenChange={setCompetitionFormOpen}
          />
        ) : (
          ActiveDomainScreen && <ActiveDomainScreen />
        )}
      </main>

      <footer className="status-strip">
        <span>No background tasks.</span>
      </footer>
    </div>
  );
}
