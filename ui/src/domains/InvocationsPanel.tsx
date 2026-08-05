import { useEffect, useState } from "react";
import { callOperation, ApiError } from "../api/client";
import type { InvocationListItem, InvocationListResponse } from "../generated/invocation";
import type { ExplainInvocationResponse } from "../generated/explain";
import "./InvocationsPanel.css";

/**
 * Invocations (09_UI §12, System domain): "the agent run history
 * (`invocation` table): outcome badges, durations, costs; each row opens
 * `kang explain`." Added 2026-08-05 alongside `invocation.list` — the
 * biggest remaining §12 gap (`InvocationStore` had no list method at
 * all before this, unlike Activity/Health's pure-exposure additions).
 *
 * No cost column: M4/M5 are zero-model by construction, the same gap
 * HealthPanel's Ledger note already names. Duration is computed from
 * `started`/`finished` client-side; "running" while `finished` is null.
 *
 * "Each row opens `kang explain`": there is no standalone explain view
 * anywhere in the UI yet (09_UI §11 names the contract, nothing renders
 * it). Rather than leaving that as a second unbuilt gap on top of the
 * list itself, a row click expands in place and calls the already-built
 * `explain.invocation` operation — the real reconstruction (trigger,
 * manifest, audit chain), not a placeholder. This is the first renderer
 * of that operation's result; a dedicated §11 explain view for other
 * subjects (plan items, notifications, memory) remains unbuilt.
 */
type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; response: InvocationListResponse };

type ExplainState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; explain: ExplainInvocationResponse };

function duration(inv: InvocationListItem): string {
  if (!inv.finished) return "running…";
  const ms = new Date(inv.finished).getTime() - new Date(inv.started).getTime();
  if (!Number.isFinite(ms) || ms < 0) return "—";
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

function outcomeClass(outcome: string | null): string {
  if (!outcome) return "invocations__badge--pending";
  return `invocations__badge--${outcome}`;
}

export default function InvocationsPanel() {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [expanded, setExpanded] = useState<string | null>(null);
  const [explain, setExplain] = useState<ExplainState | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const response = await callOperation<InvocationListResponse>(
          "invocation.list",
          {},
        );
        if (!cancelled) setState({ status: "ready", response });
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

  async function toggleRow(inv: InvocationListItem) {
    if (expanded === inv.id) {
      setExpanded(null);
      setExplain(null);
      return;
    }
    setExpanded(inv.id);
    setExplain({ status: "loading" });
    try {
      const result = await callOperation<ExplainInvocationResponse>(
        "explain.invocation",
        { correlation_id: inv.correlation_id },
      );
      setExplain({ status: "ready", explain: result });
    } catch (err) {
      const message = err instanceof ApiError ? err.envelope.message : String(err);
      setExplain({ status: "error", message });
    }
  }

  return (
    <section aria-label="Invocations" className="invocations">
      <h3 className="invocations__heading">Invocations</h3>

      {state.status === "loading" && <p className="invocations__status">Loading…</p>}
      {state.status === "error" && (
        <p className="invocations__status invocations__status--error">{state.message}</p>
      )}
      {state.status === "ready" && state.response.invocations.length === 0 && (
        <p className="invocations__status">No invocations recorded yet.</p>
      )}
      {state.status === "ready" && state.response.invocations.length > 0 && (
        <ul className="invocations__list">
          {state.response.invocations.map((inv) => (
            <li key={inv.id} className="invocations__row">
              <button
                type="button"
                className="invocations__summary"
                onClick={() => toggleRow(inv)}
                aria-expanded={expanded === inv.id}
              >
                <span className={`invocations__badge ${outcomeClass(inv.outcome)}`}>
                  {inv.outcome ?? "pending"}
                </span>
                <span className="invocations__operation">{inv.operation}</span>
                <span className="invocations__meta">
                  {inv.principal} · {inv.trigger} · {duration(inv)}
                </span>
              </button>

              {expanded === inv.id && explain && (
                <div className="invocations__explain">
                  {explain.status === "loading" && (
                    <p className="invocations__status">Reconstructing…</p>
                  )}
                  {explain.status === "error" && (
                    <p className="invocations__status invocations__status--error">
                      {explain.message}
                    </p>
                  )}
                  {explain.status === "ready" && (
                    <>
                      <p className="invocations__explain-line">
                        Reconstructed from {explain.explain.reconstructed_from}.
                      </p>
                      {explain.explain.manifest && (
                        <pre className="invocations__manifest">
                          {explain.explain.manifest}
                        </pre>
                      )}
                      {explain.explain.chain.length === 0 ? (
                        <p className="invocations__status">
                          No audit entries for this correlation.
                        </p>
                      ) : (
                        <ul className="invocations__chain">
                          {explain.explain.chain.map((entry, i) => (
                            <li key={i} className="invocations__chain-entry">
                              <span className="invocations__at">{entry.at}</span>
                              <span className="invocations__line">
                                {entry.principal} · {entry.action}
                              </span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
