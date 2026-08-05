import { useEffect, useState } from "react";
import { callOperation, ApiError } from "../api/client";
import PermissionsPanel from "./PermissionsPanel";
import "./SystemScreen.css";

/**
 * System domain (09_UI §2/UI-001, §7 permission screen, §12 Audit &
 * History Views). `registry.get` is fully real — this screen exposes the
 * served contract (operations, versions, scopes), genuinely useful
 * System-domain content (12_API §16: "the registry is the contract").
 * The permission screen itself (§7's "what can KANG touch?") is
 * `PermissionsPanel`, rendered below — its own file since it's a
 * distinct 09_UI-named concern with its own data source
 * (`permission.list`).
 *
 * Hand-typed, not generated: `registry.get` carries no `request_schema`/
 * `response_schema` in `kang.api.registry.OPERATIONS` (it predates
 * ADR-010's rollout and was never in scope for it), so ADR-011's
 * generator has nothing to emit for it. This interface mirrors
 * `registry_snapshot()`'s actual return shape
 * (`src/kang/api/registry/__init__.py`) by hand instead.
 *
 * 09_UI §12 also names Activity (audit stream), Invocations (run
 * history), Ledger (model spend), and Health (job/backup status) as
 * System-domain views. `InvocationStore`/`AuditLog`/`JobStore` do have
 * real list-capable read methods already (`by_correlation` aside,
 * `AuditLog.records()`/`months()` and `JobStore.list_jobs()` genuinely
 * exist) — but wiring them into operations means restructuring where
 * `composition.py` constructs the job store and kill switch (currently
 * built inside `_wire_scheduler`, which runs after handler wiring and can
 * return `None`), which is bigger than an in-place exposure like
 * `deadline.list` was. Flagged as real, scoped-out follow-up work, not
 * built this pass.
 */

interface RegistryOperation {
  name: string;
  kind: string;
  scope: string | null;
  idempotency: string;
  version_introduced: string;
  deprecated: boolean;
  summary: string;
  first_party_only: boolean;
  commit_mode: string | null;
}

interface RegistrySnapshot {
  contract_version: number;
  operations: RegistryOperation[];
  event_types: string[];
  error_codes: string[];
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; registry: RegistrySnapshot };

export default function SystemScreen() {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const registry = await callOperation<RegistrySnapshot>(
          "registry.get",
          {},
        );
        if (!cancelled) setState({ status: "ready", registry });
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

  if (state.status === "loading") {
    return <p className="system__status">Loading the registry…</p>;
  }

  if (state.status === "error") {
    return <p className="system__status system__status--error">{state.message}</p>;
  }

  const { registry } = state;

  return (
    <section aria-label="System" className="system">
      <h2 className="system__heading">System</h2>
      <p className="system__summary">
        Contract version {registry.contract_version} · {registry.operations.length}{" "}
        operation(s) registered
      </p>

      <div className="system__table-scroll">
        <table className="system__table">
          <thead>
            <tr>
              <th>Operation</th>
              <th>Kind</th>
              <th>Scope</th>
              <th>Summary</th>
            </tr>
          </thead>
          <tbody>
            {registry.operations.map((op) => (
              <tr key={op.name}>
                <td>{op.name}</td>
                <td>{op.kind}</td>
                <td>{op.scope ?? "—"}</td>
                <td>{op.summary}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="system__note">
        Activity, Invocations, Ledger, and Health (09_UI §12) aren't built
        yet — their underlying stores have real read methods, but exposing
        them needs a scheduler-wiring change beyond this pass.
      </p>

      <PermissionsPanel />
    </section>
  );
}
