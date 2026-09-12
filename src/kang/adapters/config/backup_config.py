"""kang.toml loader — the Kang-configured off-machine backup marker (07
Part XII.5, ADR-034).

Layer: adapters/config.
Constitutional home: 07_DATABASE Part XII.5 ("KANG's own duty ends at
`backups/`; the health panel warns (weekly) if `%KANG_HOME%` shows no
evidence of external backup... on a Kang-configured marker"), 04_ARCH
D003 (config is TOML, diffable, hand-editable in recovery).

Deliberately tolerant, unlike `planner_config.py`'s fail-closed
`load_planner_triggers`: a missing or malformed `[backup]` section reads
as "Kang has not configured a marker yet" (`None`), never a startup
failure. Planner triggers are safety-critical scheduling truth — an
invented trigger time fires automation nobody chose. A missing marker
path has the opposite risk profile: it IS the honest, correct "stale"
answer (07 Part XII.5: "KANG cannot force this; it can refuse to let it
be forgotten"), and a config typo here must not be able to take down
`morning_plan`/`deadline_sweep`/`backup.snapshot`'s own scheduling by
raising where `_wire_scheduler` cannot recover (ADR-006/07 F8's
fail-closed reasoning stays scoped to genuinely safety-critical config).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

__all__ = ["load_external_backup_marker", "parse_external_backup_marker"]


def parse_external_backup_marker(toml_text: str) -> Path | None:
    """`[backup] external_marker_path` — the file Kang's own off-machine
    backup process is expected to touch. Absent, malformed TOML, or a
    non-string/empty value all read as "not configured yet" (`None`) —
    the same honest state a configured-but-never-written marker reads as
    downstream (`BackupService.external_backup_status`)."""
    try:
        data = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError:
        return None
    backup = data.get("backup")
    if not isinstance(backup, dict):
        return None
    raw = backup.get("external_marker_path")
    if not isinstance(raw, str) or not raw:
        return None
    return Path(raw)


def load_external_backup_marker(path: Path) -> Path | None:
    """Load from `path` (`%KANG_HOME%/config/kang.toml`). A missing or
    unreadable kang.toml also reads as "not configured" here —
    `_wire_scheduler` already owns the fail-closed decision for that
    file's absence everywhere else; this loader only ever returns `None`
    on its own account, never raises."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return parse_external_backup_marker(text)
