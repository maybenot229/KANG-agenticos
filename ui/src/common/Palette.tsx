import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import "./Palette.css";

/**
 * The command palette (09_UI §10, Decision UI-002 — "one palette, three
 * registers"). Opens from anywhere in the app (Ctrl+K, App.tsx's window
 * listener, or clicking the top-bar hint) — a keyboard-first covenant
 * (UI-P6), not a confirmation: 09_UI §3 reserves true modal dialogs for
 * exactly two things (consequential confirmations, destructive
 * warnings), so this is a dismiss-anytime overlay, not `ConfirmDialog`'s
 * visual language reused — its own look entirely.
 *
 * **Navigate** — the eight real locations (Dashboard + seven domains),
 * pure client-side string matching, zero network (UI-002: "navigate...
 * P0-local").
 *
 * **Act** — "registered commands... each maps 1:1 to an API operation."
 * Scoped to exactly one real, complete command this pass: "New task…",
 * which opens the existing QuickCapture panel rather than reimplementing
 * task-creation input a second time (the same one-concept-one-
 * implementation discipline `useQuickCapture` already established).
 * `deadline.create`/`plan.generate` are real operations too, but neither
 * has a UI form/refresh-plumbing built yet to drive from here honestly —
 * added when that exists, not stubbed now.
 *
 * **Find** — 06_MEMORY's hybrid search doesn't exist yet (the memory
 * domain is an empty stub); this register says so rather than returning
 * fabricated results (UI-002: "find degrades... per 07_DATABASE F6
 * behavior" — degrades to nothing-built-yet is still a degrade, not a
 * failure, and is stated plainly, not hidden).
 */

export type PaletteLocation = string;

interface ActCommand {
  id: string;
  label: string;
  run: () => void;
}

export default function Palette({
  locations,
  currentLocation,
  onNavigate,
  onOpenCapture,
  onClose,
}: {
  locations: readonly PaletteLocation[];
  currentLocation: PaletteLocation;
  onNavigate: (location: PaletteLocation) => void;
  onOpenCapture: () => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const navigateResults = useMemo(() => {
    const q = query.trim().toLowerCase();
    return locations.filter((location) => location.toLowerCase().includes(q));
  }, [locations, query]);

  const actCommands: ActCommand[] = useMemo(
    () => [
      {
        id: "new-task",
        label: "New task…",
        run: () => {
          onOpenCapture();
          onClose();
        },
      },
    ],
    [onOpenCapture, onClose],
  );

  const actResults = useMemo(() => {
    const q = query.trim().toLowerCase();
    return actCommands.filter((command) => command.label.toLowerCase().includes(q));
  }, [actCommands, query]);

  // One flat, selectable list across both registers — Find has no
  // selectable items (it's a status line, not results) — so arrow-key
  // navigation and Enter only ever need to reason about these two.
  const flatResults = [
    ...navigateResults.map((location) => ({ kind: "navigate" as const, location })),
    ...actResults.map((command) => ({ kind: "act" as const, command })),
  ];

  useEffect(() => {
    setSelected(0);
  }, [query]);

  function runSelected(index: number) {
    const result = flatResults[index];
    if (!result) return;
    if (result.kind === "navigate") {
      onNavigate(result.location);
      onClose();
    } else {
      result.command.run();
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      onClose();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelected((i) => Math.min(i + 1, flatResults.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelected((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      runSelected(selected);
    }
  }

  return (
    <div className="palette-backdrop" onClick={onClose}>
      <div
        className="palette"
        role="dialog"
        aria-label="Command palette"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          ref={inputRef}
          className="palette__input"
          placeholder="Navigate, act, or find…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
        />

        <div className="palette__results">
          {navigateResults.length > 0 && (
            <div className="palette__register">
              <p className="palette__register-label">Navigate</p>
              <ul className="palette__list">
                {navigateResults.map((location) => {
                  const index = flatResults.findIndex(
                    (r) => r.kind === "navigate" && r.location === location,
                  );
                  return (
                    <li key={location}>
                      <button
                        type="button"
                        className="palette__item"
                        aria-selected={index === selected}
                        onClick={() => runSelected(index)}
                      >
                        {location}
                        {location === currentLocation ? " (current)" : ""}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}

          {actResults.length > 0 && (
            <div className="palette__register">
              <p className="palette__register-label">Act</p>
              <ul className="palette__list">
                {actResults.map((command) => {
                  const index = flatResults.findIndex(
                    (r) => r.kind === "act" && r.command.id === command.id,
                  );
                  return (
                    <li key={command.id}>
                      <button
                        type="button"
                        className="palette__item"
                        aria-selected={index === selected}
                        onClick={() => runSelected(index)}
                      >
                        {command.label}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}

          <div className="palette__register">
            <p className="palette__register-label">Find</p>
            <p className="palette__find-note">
              Memory/vault search isn't available yet — 06_MEMORY's search
              layer doesn't exist.
            </p>
          </div>

          {flatResults.length === 0 && (
            <p className="palette__empty">No navigate or act matches.</p>
          )}
        </div>
      </div>
    </div>
  );
}
