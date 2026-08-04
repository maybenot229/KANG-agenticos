"""Request/response schema modules for the Operation Registry (ADR-010).

Layer: api.
Constitutional home: ADR-010 Ruling 1 (one file per registry operation-name
prefix that has real handlers in `operations.py`; `held_action.*` excluded
until its handlers exist — see docs/guides/audit-2026-07-31-held-action-gap.md,
and 12_API §2/§16). Grouping follows the registry's operation-name prefixes,
not `domain/`'s area list — the two are different sets (`held_action`,
`explain` are API-layer concepts with no matching `domain/` area), and this
must not be "corrected" to match `domain/`'s folders (ADR-010 Ruling 1's 1A
bullet, verbatim).

Only `task.py` is populated as of this commit — a proof of pattern on two
operations (`task.create`, `task.get`), per ADR-010's Consequences ("the
pattern is set on the first 1-2 operations and confirmed correct, then
applied to the remaining twelve"). The other modules in this package are
placeholders naming what each will hold, mirroring this codebase's existing
not-yet-built convention (e.g. `kernel/router/__init__.py`,
`adapters/openai/__init__.py`).
"""

from __future__ import annotations

__all__: list[str] = []
