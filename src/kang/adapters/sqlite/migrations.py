"""Migrations harness — versioned, forward-only, checksummed schema history.

Layer: adapters/sqlite.
Constitutional home: 07_DATABASE Part XIII: migrations are files
``migrations/NNNN_description.sql``; forward-only (D016 — rollback is
restore-from-snapshot, never a down-migration); each applied migration's
checksum is stored and verified — a modified historical migration is a
startup-blocking error (the past is immutable). The staged apply-on-copy
protocol (XIII.3) arrives with the updater at M1+; this harness is the
mechanism it will drive.

schema_version is bootstrapped here (07 §5.5 defines its shape; the harness
owns its creation — a migration cannot record itself into a table it has
not yet created).
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from kang.domain.ports.clock import Clock

__all__ = ["Migration", "MigrationError", "apply_migrations", "discover"]

_FILENAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")

_SCHEMA_VERSION_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL,
  checksum TEXT NOT NULL             -- of the migration file, verified on startup
)
"""


class MigrationError(Exception):
    """The migration set is inconsistent with history. Startup-blocking."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path
    checksum: str


def discover(migrations_dir: Path) -> list[Migration]:
    """Return the shipped migration set, ordered, gap- and duplicate-checked."""
    found: dict[int, Migration] = {}
    for path in sorted(migrations_dir.glob("*.sql")):
        match = _FILENAME.match(path.name)
        if not match:
            raise MigrationError(
                f"{path.name}: migration files are NNNN_description.sql "
                "(07 Part XIII.1)"
            )
        version = int(match.group(1))
        if version in found:
            raise MigrationError(f"duplicate migration version {version:04d}")
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        found[version] = Migration(version, path.stem, path, checksum)
    ordered = [found[v] for v in sorted(found)]
    for position, migration in enumerate(ordered, start=1):
        if migration.version != position:
            raise MigrationError(
                f"migration versions must be gapless from 0001; "
                f"expected {position:04d}, found {migration.version:04d}"
            )
    return ordered


def _verify_history(
    conn: sqlite3.Connection, shipped: dict[int, Migration]
) -> list[int]:
    applied: list[int] = []
    rows = conn.execute(
        "SELECT version, checksum FROM schema_version ORDER BY version"
    ).fetchall()
    for version, checksum in rows:
        migration = shipped.get(version)
        if migration is None:
            raise MigrationError(
                f"applied migration {version:04d} is missing from the shipped "
                "set (the past is immutable — 07 Part XIII.4)"
            )
        if migration.checksum != checksum:
            raise MigrationError(
                f"migration {version:04d} was modified after being applied "
                "(checksum mismatch — 07 Part XIII.4)"
            )
        applied.append(version)
    return applied


def apply_migrations(
    conn: sqlite3.Connection, migrations_dir: Path, clock: Clock
) -> list[int]:
    """Bring the database to the head of the migration chain.

    Verifies existing history first (checksum immutability), then applies
    each pending migration in its own transaction, recording version +
    checksum. Returns the versions applied in this run.
    """
    migrations = discover(migrations_dir)
    conn.execute(_SCHEMA_VERSION_DDL)
    applied = set(_verify_history(conn, {m.version: m for m in migrations}))

    newly_applied: list[int] = []
    for migration in migrations:
        if migration.version in applied:
            continue
        # One atomic script per migration: DDL + the history row commit
        # together or not at all. executescript cannot parametrize, so the
        # (internally generated: int / ISO timestamp / hex digest) values are
        # inlined as literals.
        script = (
            "BEGIN IMMEDIATE;\n"
            f"{migration.path.read_text(encoding='utf-8')}\n"
            "INSERT INTO schema_version (version, applied_at, checksum) "
            f"VALUES ({migration.version}, '{clock.now().isoformat()}', "
            f"'{migration.checksum}');\n"
            "COMMIT;"
        )
        try:
            conn.executescript(script)
        except sqlite3.Error as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise MigrationError(
                f"migration {migration.version:04d} failed: {exc}"
            ) from exc
        newly_applied.append(migration.version)
    return newly_applied
