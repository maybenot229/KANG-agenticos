import "./App.css";

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
 * component owns layout only — no truth, no domain logic (UI-P1). Zone
 * content (Today's Quests, etc.) is a later slice; this scaffold proves
 * the structural contract renders before any real data is wired in.
 */
export default function App() {
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
        <button type="button" className="left-rail__capture">
          + Quick capture
        </button>
      </nav>

      <main className="content-area">
        <p className="content-area__placeholder">
          Dashboard zones land in the next slice.
        </p>
      </main>

      <footer className="status-strip">
        <span>No background tasks.</span>
      </footer>
    </div>
  );
}
