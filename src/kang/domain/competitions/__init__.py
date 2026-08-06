"""Competitions, deadlines, timeline back-planning.

Layer: domain.
Constitutional home: 02_PRD capability cluster; 07_DATABASE §5.2 (built at M5 — 18 §3).

`competition_service.py` (added 2026-08-06, ADR-014): tracking only —
create + list of a competition Kang already knows about. Discovery,
evaluation, and scouting (the `evaluation`/`result` columns) remain
Phase 3; see that module's own docstring for the exact scope line.
"""

__all__: list[str] = []
