# Audit — held_action.approve / held_action.cancel: what exists vs. what's needed end-to-end

**Date:** 2026-07-31
**Scope:** factual gap list only, per ADR-001 (held-action crash-semantics) and ADR-002 (approval channel). No opinions, no recommendations, no fixes.
**Method:** direct file reads, `grep -rn` across `src/`, `tests/`, `migrations/`. Every claim below cites file:line or the absence of any match.

---

## 1. What exists today

### 1.1 Data plumbing (complete)

- `src/kang/domain/ports/held_action.py` — full port: `HeldAction` dataclass (id, operation, action, principal, reason, reversibility, correlation_id, created_at, expires_at, status), `HeldActionStore` Protocol with `create`, `get`, `approve`, `cancel`, `mark_executed`, `approved_not_executed`, `expire_due`, `pending`. `HELD_ACTION_STATUSES = ("pending", "approved", "executed", "cancelled")` (`held_action.py:34`).
- `src/kang/adapters/sqlite/held_action_store.py` — real SQLite implementation of the port.
- `src/kang/adapters/fakes/held_action_store.py` — in-memory fake implementation.
- `migrations/0002_held_action.sql` — original table (3-state: pending/approved/cancelled).
- `migrations/0005_held_action_lifecycle.sql` — adds `executed` state and an `operation` column, per ADR-001 Decision §2 + Amendment. Comment at the top of this migration states plainly: *"No data exists in `held_action` at this schema version (the feature has no live callers yet, 12_API §7 handlers unwired)"* (`migrations/0005_held_action_lifecycle.sql:12-14`) — this is the migration's own author confirming the gap this audit documents.
- `tests/fixtures/held_action_store_contract.py` + `tests/integration/sqlite/test_held_action_store.py` + `tests/unit/kang/adapters/fakes/test_held_action_store_fake.py` — both store implementations pass a shared conformance suite. The store layer itself is tested and correct in isolation.

### 1.2 API contract layer (partial)

- `src/kang/api/registry/__init__.py:148-163` — both operations are registered:
  ```
  _op("held_action.approve", "command", None, True,
      "Approve a pending held action; drives its effect per commit_mode.",
      channel=OperationChannel(first_party_only=True))
  _op("held_action.cancel", "command", None, True,
      "Decline a pending held action.",
      channel=OperationChannel(first_party_only=True))
  ```
  The comment immediately above (`registry/__init__.py:142-147`) states: *"Handlers are not yet wired into the composition root (no held-action feature is live end-to-end); these entries register the contract shape ahead of that wiring."*
- Neither entry passes `commit_mode` to `OperationChannel(...)` — both calls set only `first_party_only=True`; `commit_mode` defaults to `None` (`registry/__init__.py:59`). **This contradicts ADR-001 Amendment's Schema/Registry section**, which states: *"`commit_mode` is a required field, enum `transactional | redrive`, on every consequential operation"* (`docs/adr/001-held-action-crash-semantics.md:205-206`). As registered today, both operations declare no commit mode at all.
- `src/kang/api/errors.py:21-35` — `first_party_required` exists in the closed `ERROR_CODES` enum (`errors.py:26`), correctly distinct from `permission_denied`, matching ADR-002 Amendment §3.
- `src/kang/api/dispatch.py:154-165` (`_authorize_channel`) — the channel gate itself is implemented and functioning: checks `entry["first_party_only"]`, raises `ApiError("first_party_required", ...)` if the session isn't first-party. This runs for *any* operation with `first_party_only=True`, including `held_action.approve`/`.cancel` — this part of ADR-002's mechanism is real and works.
- `tests/unit/kang/api/test_dispatch.py:58,156-176` — the channel gate is tested using `"held_action.approve"` as the operation name, but with a **fake stand-in handler** (`ok_handler`, line 58) substituted into the dispatcher's handler map for the test — not the real handler, because no real handler exists (see §2 below).

### 1.3 Handler layer

- `grep -rn "held_action" src/kang/api/operations.py` — **zero matches.** `operations.py` has no `make_held_action_approve_handler` or `make_held_action_cancel_handler` function, nor any reference to `held_action` at all.
- `grep -rn "held_action\|HeldAction" src/kang/kernel/runtime/composition.py` — **zero matches.** `HeldActionStore` (fake or sqlite) is never instantiated, never imported, and never wired into the handler map that `Dispatcher` receives at composition time.

### 1.4 Producer side (the other end of the flow)

- `grep -rn "confirmation_required" src/` — the only matches are: a docstring line in `errors.py:7`, the string's presence in the `ERROR_CODES` tuple (`errors.py:27`), a comment in `registry/__init__.py:51`, and a docstring line in `held_action.py:5`. **No code path anywhere in `src/` ever raises or returns `confirmation_required`.** No existing command creates a `HeldAction` row. There is currently no consequential command in the system that would trigger the approval flow `held_action.approve` is meant to resolve.

---

## 2. What's missing for held_action.approve / held_action.cancel to work end-to-end

1. **No handler functions exist.** `operations.py` needs `make_held_action_approve_handler` and `make_held_action_cancel_handler` (or equivalent), following the existing `(context, params) -> dict` handler shape used by every other operation in that file.
2. **No composition-root wiring.** `composition.py` never constructs a `HeldActionStore` (sqlite or otherwise) and never adds the two operations to the handler map passed to `Dispatcher`. Calling either operation today would fail at `Dispatcher._execute` with a `KeyError` on `self._handlers[entry["name"]]` (`dispatch.py:172`), since no such handler is registered — the failure mode is unhandled, not a typed `ApiError`.
3. **`commit_mode` is not set on either registry entry**, despite ADR-001 Amendment requiring it on every consequential operation. Per that same amendment, `commit_mode="redrive"` cannot be registered until "its target adapter has a proven idempotency contract + conformance test" — a registration-time check already enforced in code (`registry/__init__.py:166-176`) for any entry that *does* declare `redrive`. Since neither `held_action.approve` nor `held_action.cancel` declares a `commit_mode` at all right now, this enforcement loop never runs against them — the gate exists but has nothing to check yet.
4. **No effect-driving logic.** ADR-001 Decision §2/§3 requires approval to drive the held effect through "the same idempotent command path every effect already uses," and mark the row `executed` on completion, or leave it `approved` for redrive-on-restart. None of this exists: no code resolves a `HeldAction.operation` string back to a dispatchable command, no code calls `mark_executed`, and no code implements the `approved_not_executed()` redrive sweep ADR-001 §4 requires on restart. `HeldActionStore.mark_executed` and `approved_not_executed()` are implemented at the store layer (tested) but have zero callers anywhere in `src/`.
5. **No producer creates a `HeldAction` in the first place.** As shown in §1.4, no consequential command in the system currently returns `confirmation_required` or calls `HeldActionStore.create(...)`. Even if `held_action.approve` were fully wired, there would be nothing in the approval queue to approve — the entire consequential-command family described in 05_AGENTS Appendix D has not yet been built as commands that use this gate.
6. **No 24h expiry sweep is wired.** `HeldActionStore.expire_due(now)` exists at the store layer (tested) but `grep -rn "expire_due" src/` outside the store/port files returns no callers — no scheduled job invokes it.

---

## 3. Summary table

| Layer | Status | Evidence |
|---|---|---|
| Domain port (`HeldActionStore` protocol) | **Built, tested** | `domain/ports/held_action.py` |
| SQLite adapter | **Built, tested** | `adapters/sqlite/held_action_store.py`, `tests/integration/sqlite/test_held_action_store.py` |
| Fake adapter | **Built, tested** | `adapters/fakes/held_action_store.py`, `tests/unit/kang/adapters/fakes/test_held_action_store_fake.py` |
| Schema/migrations | **Built** (0002 + 0005) | `migrations/0002_held_action.sql`, `migrations/0005_held_action_lifecycle.sql` |
| Registry entries (`held_action.approve`/`.cancel`) | **Registered, incomplete** | `registry/__init__.py:148-163` — missing `commit_mode` |
| Channel gate (`first_party_only` enforcement) | **Built, tested** | `dispatch.py:154-165`, `test_dispatch.py:156-176` (via fake handler) |
| Error code (`first_party_required`) | **Built** | `errors.py:21-35` |
| Handler functions | **Missing entirely** | zero matches in `operations.py` |
| Composition-root wiring | **Missing entirely** | zero matches in `composition.py` |
| Effect-driving / redrive logic | **Missing entirely** | `mark_executed`, `approved_not_executed` have zero callers outside store/port/tests |
| Producer (any command emitting `confirmation_required` / creating a `HeldAction`) | **Missing entirely** | zero matches for `confirmation_required` as a raised value anywhere in `src/` |
| 24h expiry sweep wiring | **Missing entirely** | `expire_due` has zero callers outside store/port/tests |

**Bottom line:** the data plumbing and the channel-security mechanism are both fully built and independently tested. The command-dispatch integration (handlers, composition wiring, effect-driving, redrive, expiry sweep, and — most fundamentally — any producer that would ever create a `HeldAction` in the first place) does not exist anywhere in the codebase.
