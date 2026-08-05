import { useEffect, useState } from "react";
import { callOperation, ApiError } from "../api/client";
import type { SystemHealthResponse } from "../generated/system";
import "./HealthPanel.css";

/**
 * Health (09_UI §12, System domain): job statuses + the automation
 * kill-switch, added 2026-08-05. `system.health` exposes `JobStore.
 * list_jobs()`/`.consecutive_failures()` and `KillSwitch.is_engaged()` —
 * all pre-existing store methods, no new domain logic.
 *
 * NOT covered (09_UI §12 also names these): backup age, last restore-
 * verification result, index parity, the integrity-incident counter.
 * No port/store tracks any of them yet — a real, named gap, not folded
 * silently into "Health built."
 */
type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; health: SystemHealthResponse };

export default function HealthPanel() {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const health = await callOperation<SystemHealthResponse>(
          "system.health",
          {},
        );
        if (!cancelled) setState({ status: "ready", health });
      } catch (err) {
        if (cancelled) return;
        const message = err instanceof ApiError ? err.envelope.message : String(err);
        setState({ status: "error", message });
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section aria-label="Health" className="health">
      <h3 className="health__heading">Health</h3>

      {state.status === "loading" && <p className="health__status">Loading…</p>}
      {state.status === "error" && (
        <p className="health__status health__status--error">{state.message}</p>
      )}
      {state.status === "ready" && (
        <>
          <p className="health__automation">
            Automation:{" "}
            {state.health.automation_engaged ? "paused (kill-switch engaged)" : "running"}
          </p>
          {state.health.jobs.length === 0 ? (
            <p className="health__status">No jobs registered.</p>
          ) : (
            <ul className="health__jobs">
              {state.health.jobs.map((job) => (
                <li key={job.id} className="health__job">
                  <span className="health__job-name">{job.name}</span>
                  <span className="health__job-meta">
                    {job.schedule} · {job.catch_up}
                    {job.quarantined ? " · quarantined" : ""}
                    {job.consecutive_failures > 0
                      ? ` · ${job.consecutive_failures} consecutive failure(s)`
                      : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="health__note">
            Backup age, restore-verification, index parity, and the
            integrity-incident counter (09_UI §12) aren't tracked anywhere
            yet.
          </p>
        </>
      )}
    </section>
  );
}
