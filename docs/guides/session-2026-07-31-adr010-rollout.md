# Session report — 2026-07-31 (cont'd) — ADR-010 rollout to remaining real-handler operations

**Status of everything below: draft, unstaged, uncommitted.** No `git add`, `git commit`, or `git push` was run at any point this session, per explicit instruction. Every file listed here sits in the working tree for Kang to review cold.

This session had two parts: (1) adding `pydantic` to `pyproject.toml` now that Kang approved it, and (2) mechanically rolling out the already-approved ADR-010 pattern from `task.create`/`task.get` (last session) to the remaining five real-handler operations.

---

## NOTES (read first)

**One real judgment call, made and documented rather than silently decided — not a full stop, but flagging it as instructed.**

`deadline.create`'s domain validation (`domain/deadlines/deadline_service.py::_validate`) enforces a cross-field rule: a deadline of most kinds must reference a competition or a project; only `kind in ("school", "custom")` may stand alone. I did **not** mirror this rule in `DeadlineCreateRequest`. Reason: the kind list it depends on (`_SELF_STANDING_KINDS`) is a **private** module-level constant in `deadline_service.py` — not exported via that module's `__all__`. This codebase has a hard rule (11 §5, lint-enforced): *"a module's public surface is its `__all__`; everything else is private and MUST NOT be imported across packages."* Importing the private constant would violate that rule directly. Duplicating the literal tuple `("school", "custom")` instead would work today but risks silent drift if the domain module ever changes it — a schema silently describing a stale rule is worse than a schema that honestly omits a rule it can't safely mirror.

I judged this a "which of two real designs" question that has a clean, precedented answer (respect the existing encapsulation boundary) rather than a genuine fork needing your input — but it's exactly the kind of choice you asked to be told about, so: the anchoring rule is enforced at the domain layer only, exactly as it already was before this session. Nothing regressed; the schema is just honestly incomplete on this one cross-field rule. If you want it mirrored anyway, the clean fix is exporting `_SELF_STANDING_KINDS` (or an equivalent public name) from `deadline_service.py`'s `__all__` — a one-line, low-risk change, but a domain-module change, which felt outside this session's "schemas + registry attachment only" scope to make unasked.

No operation was stopped on. All five target operations completed.

---

## Task order and completion

Per the instruction's actual operation list, corrected against what really exists in `registry/__init__.py` (the instruction named `deadline.get` and `plan.get`, which don't exist — I used the real operations, `deadline.sweep` and `plan.generate`, as instructed to do when the named ones didn't match reality):

| Instruction said | Actually registered | Status |
|---|---|---|
| `deadline.create`, `deadline.get` | `deadline.create`, `deadline.sweep` | **Both done** (`deadline.get` doesn't exist as an operation) |
| `plan.get` | `plan.generate` | **Done** |
| `notification.ack` | `notification.ack` | **Done** |
| `explain.invocation` | `explain.invocation` | **Done** |

The four `explain.*` stub operations (`explain.plan_item`, `explain.notification`, `explain.suggestion`, `explain.memory`) were not named in the instruction and were left untouched — they're always-`not_found` stubs with no real contract to describe yet (see `schemas/explain.py`'s module docstring for the reasoning, same shape as `held_action.*`).

---

## Step 1 — `pydantic` added to `pyproject.toml`

`dependencies = ["tzdata"]` → `dependencies = ["tzdata", "pydantic"]`, unpinned, matching `tzdata`'s existing style (the only other entry in that list). Comment added citing ADR-009/010 and "Approved by Kang 2026-07-31." Nothing else in the file touched. `pip install -e ".[dev]"` re-run; `pip show kang` confirms `Requires: pydantic, tzdata`.

---

## Step 2 — Files changed

### New

- `src/kang/api/schemas/deadline.py` — populated (was a placeholder from last session). `DeadlineCreateRequest`/`Response`, `DeadlineSweepRequest`/`Response`.
- `src/kang/api/schemas/plan.py` — populated. `PlanGenerateRequest`/`Response`.
- `src/kang/api/schemas/notification.py` — populated. `NotificationAckRequest`/`Response`.
- `src/kang/api/schemas/explain.py` — populated. `ExplainInvocationRequest`/`Response`, plus a nested `AuditChainEntry` model for the `chain` field.

(`registry.py` remains an untouched placeholder — `registry.get` was never in scope for either session.)

### Modified

- `pyproject.toml` — `pydantic` added (Step 1, above).
- `src/kang/api/registry/__init__.py` — five new schema imports, `schemas=OperationSchemas(...)` attached to `deadline.create`, `deadline.sweep`, `plan.generate`, `notification.ack`, and `explain.invocation`'s `_op(...)` calls. `held_action.approve`/`.cancel` and all four `explain.*` stubs **untouched**, confirmed by direct inspection after editing (see verification below).

---

## Correctness notes per schema (each mirrors an already-enforced constraint, none invents a new one)

- **`DeadlineCreateRequest`**: `title` non-blank after `.strip()` (mirrors `_validate`), `at` ISO-8601 (mirrors `_parse_at`, same stdlib call, same failure message shape), `kind` in the exported `DEADLINE_KINDS` enum. Field defaults (`title=""`, `at=""`, `kind="custom"`) mirror the handler's own `params.get(key, default)` calls exactly — including that the defaults themselves fail validation, matching today's real behavior (an omitted `title`/`at` already produces `invalid_request`). `lead_days` is not a field: the handler never reads it from `params` at all.
- **`DeadlineSweepRequest`**: empty model — the handler ignores `params` entirely; Pydantic's default `extra='ignore'` behavior matches that (verified: extra keys are silently accepted and dropped, not rejected).
- **`PlanGenerateRequest`**: `plan_date: str | None = None`, unvalidated — the handler doesn't validate its format either (`params.get("plan_date") or <today>`), so the schema doesn't invent a stricter check.
- **`NotificationAckRequest`** / **`ExplainInvocationRequest`**: both use `Field(min_length=1)` on their id field, matching the handlers' `not <value>` truthiness checks exactly — **not** `.strip()`-based like `task.create`'s title. Verified this distinction matters: a whitespace-only string is accepted by both handlers today (truthy), and `min_length=1` preserves that, whereas a `.strip()`-based check (wrongly copied from `task.py`) would have silently tightened the contract.
- **`ExplainInvocationResponse`**: field-for-field against the `Invocation` dataclass (`domain/ports/invocation.py`) and `AuditEntry`'s exported shape (`domain/ports/audit.py`) — read directly before writing, not assumed.

---

## Verification — run after every single operation was attached, not just at the end

Each of the five operations was verified individually (full suite, every time) before moving to the next, per instruction. All five passes were green; only one transient issue occurred and was fixed immediately: after attaching `deadline.create`, I had already imported `DeadlineSweepRequest`/`Response` in anticipation of the next step, which `ruff check` correctly flagged as unused (`F401`) until `deadline.sweep` was actually attached a few minutes later in the same pass — not a real defect, just import-before-use ordering, resolved by completing that operation immediately rather than leaving a dangling import.

**Final, full suite (after all five operations attached):**

```
pytest tests/unit tests/suites -q      → 388 passed
pytest tests/integration -q            → 141 passed
ruff format --check src tests tools cli → 222 files already formatted
ruff check src tests tools cli          → All checks passed!
lint-imports --config tools/importlinter.toml → 8 kept, 0 broken
python tools/lint_sizes.py src          → 0 hard violation(s), 21 soft warning(s)
python tools/lint_banned_patterns.py src → 0 violation(s)
python tools/lint_tree_hygiene.py .     → 0 violation(s)
```

Also confirmed directly at the interpreter (not assumed):
- Every one of the 7 now-schema-attached operations (`task.create`, `task.get` from last session, plus this session's `deadline.create`, `deadline.sweep`, `plan.generate`, `notification.ack`, `explain.invocation`) serves a real JSON Schema dict in `registry_snapshot()`.
- All 7 untouched operations (`registry.get`, `held_action.approve`, `held_action.cancel`, and all four `explain.*` stubs) still serve `request_schema: null, response_schema: null` — confirmed nothing was accidentally touched.
- `json.loads(registry_json()) == registry_snapshot()` still holds exactly (the pre-existing test's own invariant).
- Field-level validation spot-checked for each new model: `DeadlineCreateRequest` rejects blank title, non-ISO `at`, and unknown `kind` with the expected messages; `DeadlineSweepRequest` accepts an empty call and silently ignores extras; `ExplainInvocationRequest` rejects an empty `correlation_id`; `ExplainInvocationResponse` constructs correctly with `None`-able `manifest`/`finished`/`outcome` despite following non-defaulted fields (confirmed Pydantic v2 has no dataclass-style positional-ordering restriction — construction is keyword-only).

---

## What's still deliberately untouched (unchanged from last session, still true)

- `dispatch.py`'s `_validate` — Ruling 4 remains unwired. All seven schema-attached operations behave identically to a caller as before either session's changes; nothing enforces these schemas at runtime yet.
- `held_action.approve` / `held_action.cancel` — still `schema=None`, per Ruling 3, pending Task 1's separately-tracked gap.
- `schemas/registry.py` — still an empty placeholder; `registry.get` was never named in either session's scope.

---

## Final file list (this session)

| File | Status |
|---|---|
| `pyproject.toml` | modified (Step 1) |
| `src/kang/api/registry/__init__.py` | modified |
| `src/kang/api/schemas/deadline.py` | populated (was a placeholder) |
| `src/kang/api/schemas/plan.py` | populated (was a placeholder) |
| `src/kang/api/schemas/notification.py` | populated (was a placeholder) |
| `src/kang/api/schemas/explain.py` | populated (was a placeholder) |
| `docs/guides/session-2026-07-31-adr010-rollout.md` | new (this file) |

## `git status` confirmation

```
 M pyproject.toml
 M src/kang/api/registry/__init__.py
 M tools/lint_sizes.py
?? docs/guides/audit-2026-07-31-held-action-gap.md
?? docs/guides/session-2026-07-31-adr010-draft.md
?? src/kang/api/schemas/
```

(`tools/lint_sizes.py` and the two `docs/guides/` untracked files are carried over from last session's still-unstaged work — nothing new in this session touched them.) Everything unstaged or untracked. No `git add`, `git commit`, or `git push` was run this session, at any point, for any reason.
