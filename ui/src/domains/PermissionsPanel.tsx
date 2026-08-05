import { useEffect, useState } from "react";
import { callOperation, ApiError } from "../api/client";
import type { PermissionListResponse } from "../generated/permission";
import "./PermissionsPanel.css";

/**
 * The permission screen (09_UI §7, System domain): "every grant per
 * principal, in the same scope language as permissions.toml, with
 * plain-language consequence lines (08_PLUGIN Appendix B style)... MUST
 * answer 'what can KANG touch?' in under a minute."
 *
 * A panel within SystemScreen, not a separate domain — 09_UI names this
 * "Permission management (System domain)" explicitly; there is no eighth
 * rail button for it.
 *
 * Read-only: this session builds viewing, not editing. 09_UI §7 itself
 * draws that line — "grant changes are themselves consequential actions"
 * — and no `grant.modify` operation exists to change one through yet.
 */

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; grants: PermissionListResponse["grants"] };

export default function PermissionsPanel() {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const response = await callOperation<PermissionListResponse>(
          "permission.list",
          {},
        );
        if (!cancelled) setState({ status: "ready", grants: response.grants });
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
    <section aria-label="Permissions" className="permissions">
      <h3 className="permissions__heading">Permissions — what can KANG touch?</h3>

      {state.status === "loading" && (
        <p className="permissions__status">Loading grants…</p>
      )}
      {state.status === "error" && (
        <p className="permissions__status permissions__status--error">
          {state.message}
        </p>
      )}
      {state.status === "ready" && state.grants.length === 0 && (
        <p className="permissions__status">No grants loaded.</p>
      )}
      {state.status === "ready" && state.grants.length > 0 && (
        <div className="permissions__list">
          {state.grants.map((grant) => (
            <div key={grant.principal} className="permissions__principal">
              <h4 className="permissions__principal-name">{grant.principal}</h4>
              <ul className="permissions__scopes">
                {grant.scopes.map((scopeGrant) => (
                  <li key={scopeGrant.scope} className="permissions__scope">
                    <code className="permissions__scope-name">
                      {scopeGrant.scope}
                    </code>
                    <span className="permissions__consequence">
                      {scopeGrant.consequence}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
