import { useState } from "react";
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

// One screen component per domain (UI-001's hub-and-spoke: domain ->
// entity -> detail, depth 3 max). Plan and System have a real backend
// today; the rest are honest empty screens (see each file's own
// docstring for exactly what's missing and why) — never fabricated
// content standing in for a domain that doesn't exist yet.
const DOMAIN_SCREENS: Record<Domain, () => JSX.Element> = {
  Plan: PlanScreen,
  Projects: ProjectsScreen,
  Competitions: CompetitionsScreen,
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

  const ActiveDomainScreen =
    location === "Dashboard" ? null : DOMAIN_SCREENS[location];

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
        <span className="top-bar__palette-hint">⌘K</span>
      </header>

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
        {ActiveDomainScreen === null ? (
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
        ) : (
          <ActiveDomainScreen />
        )}
      </main>

      <footer className="status-strip">
        <span>No background tasks.</span>
      </footer>
    </div>
  );
}
