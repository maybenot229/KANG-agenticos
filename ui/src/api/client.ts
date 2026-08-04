// The operation channel client (12_API §5) — a pure client of the local
// API (UI-P1). This is the "hand-written once, against the generated
// types" calling code ADR-011's Decision names: the generated interfaces
// (ui/src/generated/) describe request/response shapes; this file is the
// thin wire plumbing (session, POST /op, the API-006 envelope) that
// every operation shares, written once rather than generated.

import { getSession } from "./session";

export interface ApiErrorEnvelope {
  code: string;
  message: string;
  correlation_id: string;
  retryable: boolean;
  details?: Record<string, unknown>;
  remedy?: string;
}

export class ApiError extends Error {
  readonly envelope: ApiErrorEnvelope;
  constructor(envelope: ApiErrorEnvelope) {
    super(envelope.message);
    this.name = "ApiError";
    this.envelope = envelope;
  }
}

interface SuccessEnvelope<TResult> {
  ok: true;
  result: TResult;
  correlation_id: string;
}

interface FailureEnvelope {
  ok: false;
  error: ApiErrorEnvelope;
}

type ResponseEnvelope<TResult> = SuccessEnvelope<TResult> | FailureEnvelope;

/**
 * Calls one operation through the operation channel (12_API §5). Mirrors
 * `cli/kang_cli.py::_call` exactly — same session handshake, same POST
 * /op body shape, same header — a different client of the identical
 * contract, per 12_API §1 ("every interface is a client of this contract
 * and nothing else").
 *
 * A `command` (per the registry's `kind`) needs an idempotency key
 * (API-004); the caller supplies one when it matters for retry safety
 * (a create/mutate action) — this function does not silently invent one
 * for every call, since a query calling this with a stray key would be
 * harmless but misleading about which operations are commands.
 */
export async function callOperation<TResult>(
  operation: string,
  params: Record<string, unknown>,
  idempotencyKey?: string,
): Promise<TResult> {
  const session = await getSession();
  const body: Record<string, unknown> = { operation, params };
  if (idempotencyKey !== undefined) {
    body.idempotency_key = idempotencyKey;
  }
  const response = await fetch(`http://${session.host}:${session.port}/op`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Session-Token": session.token,
    },
    body: JSON.stringify(body),
  });
  const envelope: ResponseEnvelope<TResult> = await response.json();
  if (!envelope.ok) {
    throw new ApiError(envelope.error);
  }
  return envelope.result;
}

/**
 * A fresh idempotency key for one command invocation (API-004). Browsers
 * have no built-in UUIDv7 generator; `crypto.randomUUID()` (v4) is used
 * instead — the dispatcher only checks presence, never validates UUID
 * version (`dispatch.py::_validate`), so this is functionally correct.
 * Diverges from API-004's stated "UUIDv7" convention in version only, not
 * in any behavior the Core actually checks — flagged, not silently
 * matched, since API-004's choice of v7 elsewhere is deliberate
 * (time-sortability) and this client doesn't get that property.
 */
export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}
