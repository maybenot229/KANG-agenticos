"""Projects, milestones, goals.

Layer: domain.
Constitutional home: 02_PRD capability cluster; 07_DATABASE §5.2 (built at M5 — 18 §3).

`project_service.py` (added 2026-08-06, ADR-013): tracking only —
create + list. `milestone_service.py` (added 2026-08-07, ADR-015):
same tracking-only scope, per project. `goal_service.py` (added
2026-08-08, ADR-016): same tracking-only scope, self-standing (no
required FK, unlike milestone). Any status-transition on any of these
three remains unbuilt; see each module's own docstring for its exact
scope line.
"""

__all__: list[str] = []
