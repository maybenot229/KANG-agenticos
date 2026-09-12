"""SqliteBackupService against real databases (ADR-031, ADR-032).

The claim: the daily snapshot takes BOTH databases, copies the current
audit file, records one manifest line, promotes the first snapshot of a
month, and prunes to 07 Part XII's retention — and refuses, loudly,
rather than archiving suspect state.

Verify's claim (ADR-032): it opens the LATEST snapshot genuinely
read-only, runs the two named-query-suite shapes that actually exist
against it via the real production store classes, reports row counts
against live without gating on them, and returns a record — never an
exception — for a failed check; it raises only when there is nothing to
verify at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.backup_service import SqliteBackupService
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.migrations import apply_migrations
from kang.domain.ports.backup import BackupError

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"
NOW = "2026-08-17T02:30:00+00:00"


@pytest.fixture
def home(tmp_path):
    conn = open_connection(tmp_path / "kang.db")
    apply_migrations(conn, MIGRATIONS_DIR, FakeClock())
    events = open_connection(tmp_path / "events.db")
    events.execute("CREATE TABLE event (id TEXT PRIMARY KEY)")
    events.commit()
    yield tmp_path, SqliteBackupService(conn, events, tmp_path, FakeClock())
    conn.close()
    events.close()


def test_snapshot_takes_both_databases(home):
    """The event log is NOT optional: DB-001's durability pairing restores
    by replaying it for post-snapshot Tier-1 effects, so a database
    snapshot without its event log silently loses the recovery window."""
    root, service = home
    record = service.take_snapshot(NOW)
    assert Path(record.database).exists()
    assert Path(record.eventlog).exists()
    assert record.database.endswith("kang-20260817.db")
    assert record.eventlog.endswith("eventlog-20260817.db")
    assert record.bytes_total > 0


def test_snapshot_is_a_readable_database(home):
    """A snapshot nothing can open is not a backup. VACUUM INTO's output
    must carry the schema across."""
    root, service = home
    record = service.take_snapshot(NOW)
    restored = open_connection(Path(record.database))
    try:
        tables = {
            r[0]
            for r in restored.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        restored.close()
    assert {"task", "held_action", "schema_version"} <= tables


def test_manifest_records_the_run(home):
    root, service = home
    service.take_snapshot(NOW)
    lines = (root / "backups" / "manifest.jsonl").read_text(encoding="utf-8")
    entry = json.loads(lines.strip())
    assert entry["taken_at"] == NOW
    assert entry["integrity_ok"] is True
    assert entry["schema_version"] >= 1  # the real applied chain head


def test_audit_file_is_copied_when_present(home):
    root, service = home
    audit = root / "audit"
    audit.mkdir()
    (audit / "2026-08.jsonl").write_text('{"a":1}\n', encoding="utf-8")
    record = service.take_snapshot(NOW)
    assert record.audit is not None
    assert Path(record.audit).read_text(encoding="utf-8") == '{"a":1}\n'


def test_absent_audit_month_is_reported_not_invented(home):
    """No audited action yet this month — reported as None rather than
    fabricated as an empty file."""
    root, service = home
    assert service.take_snapshot(NOW).audit is None


def test_first_snapshot_of_a_month_is_promoted_and_later_ones_are_not(home):
    root, service = home
    first = service.take_snapshot("2026-08-17T02:30:00+00:00")
    assert first.promoted_monthly is not None
    assert Path(first.promoted_monthly).exists()
    second = service.take_snapshot("2026-08-18T02:30:00+00:00")
    assert second.promoted_monthly is None  # already promoted this month


def test_a_second_snapshot_on_the_same_day_is_refused(home):
    """run_once_latest should prevent it; if it happens anyway the service
    refuses rather than overwriting a snapshot already recorded."""
    root, service = home
    service.take_snapshot(NOW)
    with pytest.raises(BackupError):
        service.take_snapshot(NOW)


def test_retention_keeps_the_newest_thirty_daily(home):
    """07 Part XII.2. Names sort chronologically by construction, so the
    pruned set is the oldest — asserted by name, not by mtime."""
    root, service = home
    for day in range(1, 36):  # 35 days
        service.take_snapshot(f"2026-09-{day:02d}T02:30:00+00:00")
    kept = sorted(
        p.name
        for p in (root / "backups" / "daily").iterdir()
        if p.name.startswith("kang-")
    )
    assert len(kept) == 30
    assert kept[0] == "kang-20260906.db"  # days 1-5 pruned
    assert kept[-1] == "kang-20260935.db"


def test_retention_keeps_the_newest_twelve_monthly(home):
    root, service = home
    for month in range(1, 16):  # 15 months, each promoting once
        service.take_snapshot(f"2027-{month:02d}-01T02:30:00+00:00")
    monthly = sorted(p.name for p in (root / "backups" / "monthly").iterdir())
    assert len(monthly) == 12
    assert monthly[0] == "kang-202704.db"  # first three months pruned


def test_a_corrupt_database_is_refused_never_archived(tmp_path):
    """07 Part XV F1: suspect state is frozen, not archived.

    The corruption is deliberately PAGE-level, not header-level: a
    damaged header makes `open_connection` itself raise (verified while
    writing this test), which never reaches the service. The gate this
    exercises is the real one — a database that opens fine and only
    fails `PRAGMA integrity_check`.
    """
    db = tmp_path / "kang.db"
    conn = open_connection(db)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany(
        "INSERT INTO t (v) VALUES (?)", [(f"row-{n}" * 40,) for n in range(400)]
    )
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    raw = bytearray(db.read_bytes())
    page_size = int.from_bytes(raw[16:18], "big") or 4096
    # Shred a b-tree page well past the header, leaving the file openable.
    raw[page_size * 2 : page_size * 3] = bytes(page_size)  # zero the page
    db.write_bytes(bytes(raw))

    conn = open_connection(db)
    events = open_connection(tmp_path / "events.db")
    service = SqliteBackupService(conn, events, tmp_path, FakeClock())
    try:
        with pytest.raises(BackupError):
            service.take_snapshot(NOW)
    finally:
        conn.close()
        events.close()
    assert not (tmp_path / "backups" / "daily" / "kang-20260817.db").exists()


# ---- ADR-032: backup.verify -------------------------------------------


def test_verify_raises_when_there_is_nothing_to_verify(home):
    """Distinct from a failed check (D4): no snapshot at all is a
    structurally different condition — there is nothing to open."""
    root, service = home
    with pytest.raises(BackupError):
        service.verify_latest(NOW)


def test_verify_checks_the_latest_snapshot(home):
    root, service = home
    service.take_snapshot("2026-08-15T02:30:00+00:00")
    service.take_snapshot("2026-08-17T02:30:00+00:00")
    record = service.verify_latest("2026-08-17T03:00:00+00:00")
    assert record.snapshot.endswith("kang-20260817.db")
    assert record.integrity_ok is True


def test_verify_runs_the_real_read_shapes_against_the_snapshot(home):
    """ADR-032 D1: the two shapes that exist, exercised via the REAL
    production store classes against the restored connection — proving
    the actual read path, not a hand-duplicated query of it."""
    root, service = home
    conn = open_connection(root / "kang.db")
    try:
        conn.execute(
            "INSERT INTO deadline (id, kind, title, at, status, created_at, "
            "updated_at, device_id, revision) VALUES "
            "('d-1', 'custom', 'ship', '2026-09-01T00:00:00+00:00', 'tracked', "
            "'2026-08-17T00:00:00+00:00', '2026-08-17T00:00:00+00:00', "
            "'dev', 1)"
        )
        conn.commit()
    finally:
        conn.close()

    service.take_snapshot(NOW)
    record = service.verify_latest("2026-08-17T03:00:00+00:00")

    assert set(record.read_shapes_checked) == {"v_active_deadlines", "v_today_tasks"}
    assert record.read_shape_errors == ()
    assert record.read_shapes_not_built == ("v_project_memory", "v_contested_records")


def test_verify_reports_row_counts_without_gating_on_them(home):
    """ADR-032 D2: reported as data, never a pass/fail threshold — no
    number for "±expected churn" exists anywhere in the constitution."""
    root, service = home
    service.take_snapshot(NOW)
    conn = open_connection(root / "kang.db")
    try:
        conn.execute(
            "INSERT INTO task (id, title, status, priority, created_at, "
            "updated_at, device_id, revision) VALUES "
            "('t-1', 'new after snapshot', 'open', 3, 'c', 'u', 'dev', 1)"
        )
        conn.commit()
    finally:
        conn.close()

    # Live now has a row the snapshot does not — verify reports the
    # mismatch as data and still succeeds; nothing about the run fails.
    record = service.verify_latest("2026-08-17T03:00:00+00:00")
    assert record.live_row_counts["task"] == 1
    assert record.snapshot_row_counts["task"] == 0
    assert record.integrity_ok is True


def test_verify_of_a_corrupt_snapshot_returns_a_failed_record_not_an_exception(
    tmp_path,
):
    """D4, the central claim: a bad restore-test result is the SUCCESSFUL
    response of this operation, not a raise — collapsing it into an
    exception would hide the one finding this job exists to surface."""
    conn = open_connection(tmp_path / "kang.db")
    apply_migrations(conn, MIGRATIONS_DIR, FakeClock())
    events = open_connection(tmp_path / "events.db")
    events.execute("CREATE TABLE event (id TEXT PRIMARY KEY)")
    events.commit()
    service = SqliteBackupService(conn, events, tmp_path, FakeClock())
    service.take_snapshot(NOW)
    conn.close()
    events.close()

    snapshot = tmp_path / "backups" / "daily" / "kang-20260817.db"
    raw = bytearray(snapshot.read_bytes())
    page_size = int.from_bytes(raw[16:18], "big") or 4096
    raw[page_size * 2 : page_size * 3] = bytes(page_size)
    snapshot.write_bytes(bytes(raw))

    conn = open_connection(tmp_path / "kang.db")
    events = open_connection(tmp_path / "events.db")
    service = SqliteBackupService(conn, events, tmp_path, FakeClock())
    try:
        record = service.verify_latest("2026-08-17T03:00:00+00:00")  # does NOT raise
    finally:
        conn.close()
        events.close()
    assert record.integrity_ok is False


def test_a_verify_manifest_line_is_distinguishable_from_a_snapshot_one(home):
    root, service = home
    service.take_snapshot(NOW)
    service.verify_latest("2026-08-17T03:00:00+00:00")
    lines = [
        json.loads(line)
        for line in (root / "backups" / "manifest.jsonl")
        .read_text(encoding="utf-8")
        .strip()
        .splitlines()
    ]
    assert [entry["kind"] for entry in lines] == ["snapshot", "verify"]


# ---- ADR-033: latest_status ---------------------------------------------


def test_latest_status_of_a_fresh_home_is_all_none(home):
    """No manifest at all — a fresh Core — is the same as an empty one,
    not an error."""
    root, service = home
    status = service.latest_status()
    assert status.last_snapshot_at is None
    assert status.last_verify_at is None
    assert status.last_verify_ok is None


def test_latest_status_after_a_snapshot_with_no_verify_yet(home):
    """Two genuinely different 'nothing yet' states, not collapsed into
    one: a snapshot exists, but no verify has run yet."""
    root, service = home
    service.take_snapshot(NOW)
    status = service.latest_status()
    assert status.last_snapshot_at == NOW
    assert status.last_verify_at is None
    assert status.last_verify_ok is None


def test_latest_status_reflects_the_most_recent_of_each_kind(home):
    root, service = home
    service.take_snapshot("2026-08-15T02:30:00+00:00")
    service.verify_latest("2026-08-15T03:00:00+00:00")
    service.take_snapshot("2026-08-17T02:30:00+00:00")
    status = service.latest_status()
    assert status.last_snapshot_at == "2026-08-17T02:30:00+00:00"  # the later one
    assert status.last_verify_at == "2026-08-15T03:00:00+00:00"  # unaffected


def test_latest_status_reports_a_clean_verify_as_ok(home):
    root, service = home
    service.take_snapshot(NOW)
    service.verify_latest("2026-08-17T03:00:00+00:00")
    assert service.latest_status().last_verify_ok is True


def test_latest_status_reports_a_broken_read_shape_as_not_ok(tmp_path):
    """The central claim: integrity_ok alone is not enough — a clean
    integrity check with a broken read shape is still a failed
    restore-test by 07 Part XII.3's own standard ("every view returns").

    Renames one COLUMN (not the whole table) on the SNAPSHOT only, not
    live: `DeadlineStore.active()`'s WHERE clause needs `status`, so its
    read shape fails, while `_row_counts`'s bare `COUNT(*)` and
    `integrity_check` both stay clean — isolating the one thing this
    test means to break. (`DROP COLUMN` was tried first and refused by
    SQLite itself: the partial index on `status` depends on it — a real
    finding about the schema, not a test bug, left as this comment
    rather than silently switched away from without a trace.)
    """
    conn = open_connection(tmp_path / "kang.db")
    apply_migrations(conn, MIGRATIONS_DIR, FakeClock())
    events = open_connection(tmp_path / "events.db")
    events.execute("CREATE TABLE event (id TEXT PRIMARY KEY)")
    events.commit()
    service = SqliteBackupService(conn, events, tmp_path, FakeClock())
    service.take_snapshot(NOW)

    snap = open_connection(tmp_path / "backups" / "daily" / "kang-20260817.db")
    snap.execute("ALTER TABLE deadline RENAME COLUMN status TO status_renamed")
    snap.commit()
    snap.close()

    service.verify_latest("2026-08-17T03:00:00+00:00")
    conn.close()
    events.close()

    conn = open_connection(tmp_path / "kang.db")
    events = open_connection(tmp_path / "events.db")
    service = SqliteBackupService(conn, events, tmp_path, FakeClock())
    status = service.latest_status()
    conn.close()
    events.close()
    assert status.last_verify_ok is False
