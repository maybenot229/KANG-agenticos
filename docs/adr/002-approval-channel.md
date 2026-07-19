# ADR 002 — The approval channel: how first-party confirmation is enforced

**Status:** accepted (with amendment, 2026-07-20)
**Date:** 2026-07-20
**Batch:** B (pre-M3 ruling #4 of 5)
**Affected documents:** 12_API §7 (held_action.approve, first-party rule), 12_API API-003 (sessions/principals), 05_AGENTS §8 (permission model boundary), 10_SECURITY §5.4 / SEC-003 / SEC-004
**Cites (inlined decisions clarified/mechanized):** SEC-003 (out-of-band confirmation), SEC-004 (capabilities are the only authorization model), API-003 (no second authorization vocabulary), API-006 (one error model)
**Related:** [[001-held-action-crash-semantics]] (what happens after an approval passes this channel)

---

## Context

12_API §7 and SEC-003 require that a held action be approved **out-of-band,
from a first-party UI session only** — "plugin sessions MUST NOT approve held
actions." The M4 code laid the hook and stopped short of the decision:

- `Session.first_party: bool` exists (`session.py`), and the dispatcher threads
  it into `HandlerContext.first_party` (`dispatch.py:106`).
- **But nothing enforces it.** No operation checks `first_party`; the registry
  `_op(...)` tuple has no first-party field; and `held_action.approve` is **not
  a registered operation at all** yet (`registry/__init__.py` lists
  `registry.get`, `task.create`, `task.get`, `explain.*` — no held-action ops).

So the mechanism is genuinely undecided: the *bit* is carried, but where it is
**set**, where it is **checked**, and how it relates to the permission engine
are all open.

Underneath sits a real constitutional tension the decision must resolve, not
paper over:

- **SEC-004 / API-003:** capabilities (grants, the Permission Engine) are the
  **only** authorization model; "the API layer adds *no* second authorization
  vocabulary." Taken literally, "first-party-only" must **not** be a permission
  scope.
- **SEC-003:** consequential confirmation must be **out-of-band** — a property
  of the *channel* the approval arrives through, precisely so that an injected
  agent or a plugin, however it is granted, *cannot* self-approve.

These are not in conflict once named correctly: authorization and channel are
**orthogonal axes**. The Permission Engine answers *"may this principal perform
this operation?"* The channel check answers *"did this confirmation arrive
through the one path injection cannot reach?"* Both must hold for a
consequential approval; neither is the other.

## Options

### Option A — Imperative check inside the `held_action.approve` handler

`if not context.first_party: raise ApiError("permission_denied", …)` in the
handler body.

- **For:** trivial; local.
- **Against:** violates 12 §2 (handlers are logic-free glue to domain services;
  an authority `if` here is a defect) and scatters a **security boundary** into
  per-handler code, where the next consequential operation's author must
  remember to repeat it. Security controls that depend on discipline decay
  (13 §1.1). Rejected.

### Option B — First-party as a declared operation property, enforced centrally (recommended)

Add a boolean **`first_party_only`** to the operation registry entry (declared
like `scope`). The dispatcher enforces it in a dedicated pipeline slot, uniform
for every operation, returning the existing `permission_denied` code (API-006 —
no new error vocabulary). `Session.first_party` is **stamped by the Core at
session-mint time from the establishment method** — a token read from the
Core's session file (readable only by Kang's OS account, API-003) mints
`first_party=True`; a session minted at plugin-enable, bound to `plugin:{id}`,
mints `first_party=False`. **The client never asserts it.**

First-party is declared and enforced as a **channel** control, explicitly *not*
a permission scope — the ADR names the orthogonality so no future contributor
collapses it into a grant.

- **For:** mirrors how `scope` is declared per-operation and checked once,
  centrally (SEC-009's uniform-enforcement stance); keeps handlers logic-free;
  keeps authorization vocabulary in the engine only (API-003 satisfied — this is
  not authorization); makes "which operations are out-of-band-only" a
  **readable registry fact**, not buried code (P5, the "read a directory to know
  what KANG can do" property).
- **Against:** adds one field to the registry entry and one slot to the
  dispatcher pipeline. Both additive and conformance-testable. Accepted.

### Option C — Model first-party as a permission scope

Grant a `held_action.approve` scope to `kang` only; let the engine enforce it.

- **For:** reuses the engine; no new field.
- **Against:** violates API-003 ("no second authorization vocabulary") by
  overloading grants with a channel concern, and — the deeper error —
  **misframes the control.** The whole point of out-of-band is that the
  *channel*, not the *identity*, resists injection. A scope is identity-based;
  an injected agent running as a sufficiently-granted principal would satisfy
  it, which is exactly the attack SEC-003 exists to stop. Channel ≠ capability.
  Rejected on security grounds, not just taxonomy.

## Decision (proposed)

Adopt **Option B.**

1. **`first_party_only: bool` is a declared property of the operation
   registry entry**, alongside `scope`. It is a channel control, **not** an
   authorization scope; the Permission Engine's vocabulary is untouched
   (API-003, SEC-004 preserved).

2. **The dispatcher enforces it centrally**, in its own pipeline slot,
   *in addition to* the permission check — **both must pass** (defense in depth,
   SEC-003 §5 layer 4). A first-party-only operation invoked from a non-first-
   party session returns `permission_denied` (API-006; no new error code),
   audited like any denial.

3. **`Session.first_party` is Core-stamped at mint from the establishment
   method, never client-claimed.** Session-file token ⇒ `True`; plugin-enable
   mint ⇒ `False`. A client presenting a token cannot elevate its own
   first-party-ness; the bit is a fact about *how the session was obtained*.

4. **The entire `held_action.*` command family is first-party-only** —
   `held_action.approve` and `held_action.cancel` (decline). A plugin has no
   business touching Kang's approval queue at all; plugins interact with held
   actions only by *generating* them through their own consequential commands,
   never by approving, declining, or draining them.

5. **Name the orthogonality in-doc** (12_API §7 / 05_AGENTS §8, when applied):
   authorization = capabilities, enforced by the engine, answering *"may this
   principal?"*; channel = first-party, enforced by the dispatcher, answering
   *"did this arrive out-of-band?"*. Consequential confirmation requires both;
   neither substitutes for the other. This prevents the next contributor from
   "simplifying" one into the other.

## Consequences

- **Registry delta owed** (12_API §16 operation registry; the `_op(...)` shape
  in `registry/__init__.py`): add the `first_party_only` field. Additive; the
  M4 conformance suite (13 §2.4) gains a case: a first-party-only operation from
  a plugin session is denied. Recorded here, applied by the follow-through PR
  **after acceptance** — not now.
- **`held_action.approve` / `held_action.cancel` become registerable** as
  first-party-only commands. Their handlers stay logic-free — the channel gate
  is the dispatcher's, the effect is [[001-held-action-crash-semantics]]'s.
- **Dispatcher pipeline gains one slot** (between authenticate and authorize, or
  folded beside authorize). Small, central, uniform — the intended shape.
- **Honest limit restated (API-003 trade-off):** first-party proves "this
  session was established from Kang's OS-account-readable session file," **not**
  "Kang's own hands issued this request." Malware running *as Kang's OS user*
  can read that file and would satisfy the channel check — stated, accepted,
  out of scope (10_SECURITY §2.2). First-party raises the bar to "code running
  as Kang's account," which is the honest local-first perimeter; it does not
  claim more.
- **Pattern set for all future consequential operations:** every operation in
  05_AGENTS Appendix D's closed list declares `first_party_only=true` when it
  becomes a command. This ADR is the mechanism; ruling #5 (consequential-list
  delta) is the reconciliation of *which* operations that is.
- **What gets harder:** two independent gates (engine + channel) now guard
  consequential approval, so a future "why was this denied?" must distinguish
  *scope* denial from *channel* denial. Both return `permission_denied`; the
  audit detail names which gate refused. A small cost for defense in depth.

## Amendment — 2026-07-20 — whole family confirmed; distinct error code; check ordering

**Status:** accepted (Batch B follow-through task).

1. **`held_action.*` — approve AND cancel/decline — is `first_party_only`,
   confirmed as a single family, no split.** Sharper rationale recorded: a
   plugin canceling a pending approval is not "less risky than approving" —
   it is an out-of-mandate action regardless of risk direction (AGP-1, one
   mandate per agent; a plugin's mandate never includes managing Kang's
   approval queue). It also opens a concrete denial-of-service: a
   compromised or merely buggy plugin auto-declining Kang's time-sensitive
   confirmations before he ever sees the dialog defeats the confirmation's
   purpose as surely as auto-approving would. Both directions are in scope.

2. **Check ordering, made explicit:** the dispatcher runs `first_party_only`
   enforcement **after** the permission/scope check, not before. Both gates
   must independently pass; ordering them scope-first means a request that
   fails on capability grounds is refused for that reason first (the more
   informative refusal when both would fail), and the channel check is the
   final gate immediately before execution — closest to the effect it protects.

3. **Distinct error code, not `permission_denied`.** The base ADR's decision
   §2 text ("returns the existing `permission_denied` code... no new error
   vocabulary") is **superseded by this amendment**: channel and capability
   are orthogonal per this ADR's own Context section, and collapsing their
   failures into one error code would make an audit reader unable to tell
   *which* gate refused without re-deriving it from the denial detail — the
   opposite of SEC-010 ("explanations are mandatory for authority"). A new,
   distinct code is added to the closed enum (API-006): **`first_party_required`**
   — mirrors the existing `confirmation_required` naming pattern (states what
   the request is missing, not who was denied), distinct on sight from
   `permission_denied` in logs and audit entries. **Confirmed by Kang,
   2026-07-20** — settled in the registry (`src/kang/api/errors.py`).
