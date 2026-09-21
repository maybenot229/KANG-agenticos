"""13 §2.8 / 07 Part XVI companions to the exhaustive M-003 sweep: the integer
rowid never crosses a port (ADR-048's owed claim), `memory.saved`'s payload is
the row, and the scope vocabulary is single (ADR-051 D1)."""

from __future__ import annotations

import dataclasses
import importlib
import pkgutil
from pathlib import Path

import pytest
from pydantic import BaseModel

import kang.api.schemas as api_schemas
import kang.domain.ports as ports
from kang.adapters.fakes.clock import FakeClock
from kang.adapters.sqlite.connection import open_connection
from kang.adapters.sqlite.migrations import apply_migrations
from kang.adapters.sqlite.recovery import SqliteRecoveryApplier
from kang.api.registry import OPERATIONS
from kang.domain.memory import (
    MEMORY_EVENT_FIELDS,
    Proposal,
    build_record,
    memory_event_payload,
)
from kang.kernel.bus.event_registry import EVENT_TYPES
from tests.fixtures.event_log_contract import make_envelope

REPO_ROOT = Path(__file__).resolve().parents[3]


def _modules(package):
    for info in pkgutil.iter_modules(package.__path__):
        yield importlib.import_module(f"{package.__name__}.{info.name}")


def test_no_port_dataclass_carries_the_integer_rowid():
    """ADR-048 D2's owed claim: the rowid is storage-local to
    adapters/sqlite — no port datatype has a field for it."""
    seen = 0
    for module in _modules(ports):
        for value in vars(module).values():
            if dataclasses.is_dataclass(value) and value.__module__ == module.__name__:
                seen += 1
                names = {f.name.lower() for f in dataclasses.fields(value)}
                assert not {n for n in names if "rowid" in n}, value
    assert seen > 20  # the sweep really covered the ports


def test_no_api_schema_model_carries_the_integer_rowid():
    seen = 0
    for module in _modules(api_schemas):
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and issubclass(value, BaseModel)
                and value.__module__ == module.__name__
            ):
                seen += 1
                assert not {n for n in value.model_fields if "rowid" in n.lower()}, (
                    value
                )
    assert seen > 30


def test_no_event_payload_field_is_a_rowid():
    for name, event_type in EVENT_TYPES.items():
        assert not [f for f in event_type.required_payload_fields if "rowid" in f], name


def test_the_memory_event_payload_is_exactly_the_memory_record_columns(tmp_path):
    """One vocabulary in four places: the domain builder, the event registry,
    the recovery applier, and the migrated table."""
    conn = open_connection(tmp_path / "kang.db")
    try:
        apply_migrations(conn, REPO_ROOT / "migrations", FakeClock())
        columns = [r[1] for r in conn.execute("PRAGMA table_info(memory_record)")]
    finally:
        conn.close()
    assert [c for c in columns if c != "rowid"] == list(MEMORY_EVENT_FIELDS)
    assert EVENT_TYPES["memory.saved"].required_payload_fields == MEMORY_EVENT_FIELDS
    from kang.adapters.sqlite.recovery import _MEMORY_FIELDS

    assert _MEMORY_FIELDS == MEMORY_EVENT_FIELDS


def test_memory_saved_is_registered_recovery_grade():
    entry = EVENT_TYPES["memory.saved"]
    assert (entry.category, entry.recovery_grade) == ("domain", True)
    for unbuilt in ("memory.proposed", "memory.rejected", "memory.expired"):
        assert unbuilt not in EVENT_TYPES  # ADR-051 D7: no consumer, no event


@pytest.fixture
def conn(tmp_path):
    connection = open_connection(tmp_path / "kang.db")
    apply_migrations(connection, REPO_ROOT / "migrations", FakeClock())
    yield connection
    connection.close()


def _record(revision=1, **overrides):
    proposal = Proposal("fact", "the term ends june 12", 2, "stated", "conv", "why")
    record = build_record(proposal, "mem-1", "kang", "2026-01-01T00:00:00+00:00", "dev")
    return dataclasses.replace(record, revision=revision, **overrides)


def _saved(record):
    return make_envelope(
        0,
        type="memory.saved",
        payload=memory_event_payload(record),
        entity_refs=({"kind": "memory", "id": record.id},),
    )


def test_recovery_redoes_a_save_then_a_merge_idempotently(conn):
    """The applier's update branch (a silent merge is a `memory.saved` at a
    higher revision): id+revision keyed, re-application a no-op."""
    applier = SqliteRecoveryApplier(conn)
    first = _record()
    merged = _record(revision=2, source_detail="conv\nagent:x observed:log")
    assert applier.reapply(_saved(first)).outcome == "applied"
    assert applier.reapply(_saved(first)).outcome == "noop"
    assert applier.reapply(_saved(merged)).outcome == "applied"
    assert applier.reapply(_saved(merged)).outcome == "noop"
    assert (
        applier.reapply(_saved(first)).outcome == "noop"
    )  # stale redo never regresses
    row = conn.execute(
        "SELECT revision, source_detail, content FROM memory_record WHERE id = 'mem-1'"
    ).fetchone()
    assert row == (2, "conv\nagent:x observed:log", "the term ends june 12")
    assert applier.entity_exists("memory", "mem-1") is True


def test_the_scope_vocabulary_is_single_memory_write_is_gone():
    """ADR-051 D1: `memory.propose:{type}` is the vocabulary; 04 D013's
    `memory.write` was never implemented and appears nowhere live."""
    assert not [e for e in OPERATIONS if e["scope"] and "memory.write" in e["scope"]]
    grants = (REPO_ROOT / "config" / "defaults" / "permissions.toml").read_text(
        encoding="utf-8"
    )
    assert "memory.write" not in grants
