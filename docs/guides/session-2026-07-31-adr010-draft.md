# Session report — 2026-07-31 — ADR-010 Rulings 1/2 draft implementation

**Status of everything below: draft, unstaged, uncommitted.** No `git add`, `git commit`, or `git push` was run at any point this session, per explicit instruction. Every file listed here sits in the working tree for Kang to review cold.

---

## NOTES (read first — nothing here blocked, but three things need your eyes)

1. **`pyproject.toml` does not declare `pydantic` as a dependency, and I did not add it, per your explicit instruction.** It happens to be installed in this dev environment already (`pip show pydantic` → 2.11.10) — probably a leftover from an earlier `pip install`, not something `pyproject.toml` asked for. Everything below imports and runs correctly *here*, but a fresh clone running `pip install -e ".[dev]"` would fail with `ModuleNotFoundError: No module named 'pydantic'` the moment `kang.api.registry` is imported. ADR-010's own Consequences section (line 120) says *"pyproject.toml unaffected further (Pydantic dependency already added under ADR-009)"* — that claim is false; ADR-009 decided Pydantic, ADR-010 assumed it had already landed in code, and it hasn't. This needs a real decision from you: add `pydantic` to `dependencies` now (making this draft installable), or hold it until you're ready to commit. I did not make that call myself, per your instruction.

2. **`tools/lint_sizes.py`'s hard-limit-exception mechanism didn't exist and I had to build it.** The linter's own docstring said plainly: *"this linter recognizes none yet; the first exception adds the mechanism in the same PR."* `_op()` going to 7 parameters (Ruling 2) would otherwise have been a hard CI failure with no way to justify it. I implemented the mechanism the docstring already committed to: a function/class whose own docstring contains the literal marker `HARD-LIMIT EXCEPTION` is downgraded from a blocking hard failure to a reported soft finding. This is real, tested engineering beyond ADR-010's literal text, but I judged it non-blocking — the docstring had already decided *that* this mechanism would exist and roughly *how* ("inline justification naming an ADR or reason"); I only had to build the mechanical recognition. Verified: `python tools/lint_sizes.py src` → 0 hard violations, `_op` shows as a tagged, non-blocking soft finding.

3. **No genuine two-design fork came up in Task 2.** I expected one going in (file-layout scaffolding: create placeholder files for every real-handler prefix, or only the ones actually populated?) and resolved it myself rather than stopping, because there's direct in-repo precedent either way could point to — I went with "create all the prefix files, mostly as near-empty placeholders" because that's what ADR-010 Ruling 1 and your Task 2 instructions literally ask for, and because this codebase already has exactly this pattern elsewhere (`kernel/router/__init__.py`, `adapters/openai/__init__.py` — both are just a docstring + `__all__: list[str] = []`, citing the milestone that will populate them). If you'd have preferred *no* placeholder files until each operation's schema actually lands, that's a real, cheap-to-reverse alternative — flagging it here rather than pretending it wasn't a choice.

---

## Task 1 — held_action gap audit

**File:** [`docs/guides/audit-2026-07-31-held-action-gap.md`](audit-2026-07-31-held-action-gap.md) (new)

Plain factual audit, file:line cited throughout, no opinions. Summary: the data plumbing (port, both store adapters, both migrations) and the channel-security mechanism (`first_party_only` enforcement in `dispatch.py`) are both fully built and independently tested. Nothing else exists — no handler functions in `operations.py`, no composition-root wiring, no effect-driving/redrive logic, and (most fundamentally) no producer anywhere in `src/` that would ever create a `HeldAction` or return `confirmation_required` in the first place. Also caught: neither `held_action.approve` nor `held_action.cancel`'s registry entry declares `commit_mode`, despite ADR-001 Amendment requiring it on every consequential operation — the registration-time enforcement loop for that requirement exists in code but never runs against these two entries, since they don't set the field at all.

---

## Task 2 — ADR-010 Rulings 1 & 2, proof-of-pattern on two operations

### Files created

- `src/kang/api/schemas/__init__.py` — package docstring, `__all__ = []`.
- `src/kang/api/schemas/task.py` — **populated.** `TaskCreateRequest`, `TaskCreateResponse`, `TaskGetRequest`, `TaskGetResponse`. Field constraints mirror the domain layer's *already-enforced* invariants exactly (title non-empty after `.strip()`, priority 1–5 per `domain/tasks/task_service.py::_validate`) rather than inventing new ones — verified against the actual handler and domain code before writing, not assumed.
- `src/kang/api/schemas/deadline.py`, `plan.py`, `notification.py`, `explain.py`, `registry.py` — placeholders, one per registry-prefix with a real handler (excluding `held_action.*`, per instruction). Each just a docstring pointing at `task.py` as the pattern and noting the real content is follow-up work.

### Files modified

- `src/kang/api/registry/__init__.py`:
  - New `OperationSchemas` frozen dataclass (`request: type[BaseModel] | None`, `response: type[BaseModel] | None`), defined alongside `OperationChannel`, kept as a **distinct type** rather than fields bolted onto `OperationChannel` — per ADR-010 Ruling 2's own reasoning (channel control is ADR-002's concept, schemas are ADR-010's, conflating them blurs a boundary ADR-002 was deliberate about).
  - `_op(...)` gains one new optional parameter, `schemas: OperationSchemas | None = None` — 7 parameters total, one over 11 §4's hard limit of 6. Carries the `HARD-LIMIT EXCEPTION` marker in its own docstring (see NOTES §2 above), citing this exact justification.
  - Every entry's dict gains `request_schema` / `response_schema` keys. For the 12 untouched operations these are `None`/`None` automatically (the dataclass default), which is exactly ADR-010 Ruling 3's null-schema contract — satisfied without touching those 12 `_op(...)` calls at all.
  - New `_json_safe_operation()` helper + `registry_snapshot()` now maps over it. **This resolves a mechanical gap ADR-010 didn't spell out:** a Pydantic model *class* is not JSON-serializable, but `operation(name)` (used by dispatch, and eventually Ruling 4's validator) needs the real class, while `registry_json()` (the served contract, ADR-010 Ruling 3) needs actual JSON Schema. Resolved by keeping the raw class on `OPERATIONS`/`operation()` and converting to `.model_json_schema()` (or explicit `None`) only inside `registry_snapshot()`. Verified by direct interpreter check: `operation("task.create")["request_schema"]` returns the real `TaskCreateRequest` class; `registry_snapshot()["operations"]`'s matching entry returns a JSON Schema dict; `json.loads(registry_json()) == registry_snapshot()` still holds (the existing test's exact invariant).
  - `task.create` and `task.get` are the only two of the 14 `_op(...)` calls that now pass `schemas=OperationSchemas(...)`. The other 12, including both `held_action.*` entries, are **byte-for-byte unchanged** — confirmed by re-reading the file after editing.

- `tools/lint_sizes.py`:
  - Added `EXCEPTION_MARKER = "HARD-LIMIT EXCEPTION"` and `_has_exception_marker()`, checking a function/class's own docstring via `ast.get_docstring()`. When present, a hard-limit finding for that node is downgraded to soft (still printed, never silently dropped) — matching the "inline justification... reported in CI output, visible debt" language 11 §4 already used, and the exact mechanism this file's own docstring said didn't exist yet.

### The two chosen operations, and why

**`task.create` and `task.get`.** Both already have real, working handlers in `operations.py`. Compared against every other wired operation (`deadline.create`, `deadline.sweep`, `plan.generate`, `notification.ack`, `explain.invocation`), these two have the simplest, most directly primitive-typed params: `task.create` is `{title: str, priority: int=3}`, `task.get` is `{id: str}`. They're also in the same domain prefix, so `schemas/task.py` demonstrates the file-per-prefix pattern (Ruling 1) holding two related operations together, and demonstrates both directions of the attachment mechanism (Ruling 2) — a command with real validation logic (`task.create`) and a query with none (`task.get`) — in one small, readable file.

### Deliberately NOT done (Ruling 4, and why)

`dispatch.py`'s `_validate` method is **untouched.** ADR-010 Ruling 4 wires Pydantic validation into the live request path and defines how a `ValidationError` gets sanitized before it can appear in an `invalid_request` response's `details.field_errors` — the sanitization exists specifically to stop private-tier field values from leaking through validation errors into responses/logs/audit (D010/PRD §10.14's threat model). That's real logic-path surgery with a genuine security property riding on getting the sanitization right, and per your own instruction this session, it's exactly the kind of thing you should watch happen live rather than review after the fact. The schemas built this session exist and are correct, but nothing in `dispatch.py` calls them yet — `task.create`/`task.get` behave identically to before this session's changes from a caller's perspective.

---

## Verification performed (all local, nothing pushed)

```
pytest tests/unit tests/suites -q      → 388 passed
pytest tests/integration -q            → 141 passed
ruff format --check src tests tools cli → 222 files already formatted
ruff check src tests tools cli          → All checks passed!
lint-imports --config tools/importlinter.toml → 8 kept, 0 broken
python tools/lint_sizes.py src          → 0 hard violation(s), 21 soft warning(s)
python tools/lint_banned_patterns.py src → 0 violation(s)
python tools/lint_tree_hygiene.py .     → 0 violation(s)
python tools/build_root_docs.py --check → CLAUDE.md is current.
```

Also confirmed directly at the interpreter: schema validation rejects a blank/whitespace-only title and an out-of-range priority with the same messages the domain layer would produce; `task.get`'s empty-string `id` is accepted (matching the current handler's actual, looser behavior — not tightened); `registry_json()` round-trips to exactly `registry_snapshot()`; `held_action.approve`/`.cancel` show `request_schema: null, response_schema: null` in the served registry, satisfying Ruling 3 without any code written for them.

---

## Final file list

| File | Status |
|---|---|
| `docs/guides/audit-2026-07-31-held-action-gap.md` | new |
| `docs/guides/session-2026-07-31-adr010-draft.md` | new (this file) |
| `src/kang/api/schemas/__init__.py` | new |
| `src/kang/api/schemas/task.py` | new, populated |
| `src/kang/api/schemas/deadline.py` | new, placeholder |
| `src/kang/api/schemas/plan.py` | new, placeholder |
| `src/kang/api/schemas/notification.py` | new, placeholder |
| `src/kang/api/schemas/explain.py` | new, placeholder |
| `src/kang/api/schemas/registry.py` | new, placeholder |
| `src/kang/api/registry/__init__.py` | modified |
| `tools/lint_sizes.py` | modified |

## `git status` confirmation

```
 M src/kang/api/registry/__init__.py
 M tools/lint_sizes.py
?? docs/guides/audit-2026-07-31-held-action-gap.md
?? docs/guides/session-2026-07-31-adr010-draft.md
?? src/kang/api/schemas/
```

Everything unstaged or untracked. No `git add`, `git commit`, or `git push` was run this session, at any point, for any reason.
