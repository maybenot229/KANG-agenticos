"""Vault notes/chunks, memory records/revisions/queue, and episodes
(ADR-049 D2/D3).

Rows are placed in the states 06 allows; they are not driven through the
gate or the lifecycle (D6). `private` rows carry the literal placeholder
`[encrypted]` and random bytes as *fake* ciphertext — DB-005's mechanism is a
later slice — so `fts_memory`'s private exclusion is exercised at scale.
"""

from __future__ import annotations

import hashlib
import json

from ._ctx import CHUNK_ROWS, Ctx, Weighted, iso, later
from .profiles import (
    EPISODE_STATUSES,
    EPISODE_TYPES,
    MEMORY_TYPES,
    SENSITIVITIES,
    SOURCE_BY_TIER,
    STATUSES,
    TRUST_BY_TYPE,
)
from .text import chunk_text, estimate_tokens

_NOTE_STATUS = Weighted((("indexed", 96), ("stale", 3), ("missing", 1)))
_TYPE = Weighted(MEMORY_TYPES)
_TRUST = {t: Weighted(w) for t, w in TRUST_BY_TYPE.items()}
_SOURCE = {tier: Weighted(w) for tier, w in SOURCE_BY_TIER.items()}
_STATUS = Weighted(STATUSES)
_SENSITIVITY = Weighted(SENSITIVITIES)
_EPISODE_TYPE = Weighted(EPISODE_TYPES)
_EPISODE_STATUS = Weighted(EPISODE_STATUSES)
_QUEUE_RESOLVED = Weighted(
    ((None, 70), ("approved", 12), ("edited", 5), ("rejected", 8), ("expired", 5))
)
_QUEUE_FLAGS = Weighted((("[]", 80), ('["near_duplicate"]', 12), ('["conflict"]', 8)))
_NOTES_PER_GROUP = 80  # keeps one note+chunk transaction near 1,000 rows

_CHUNK_SQL = (
    "INSERT INTO vault_chunk (id, note_path, anchor, seq, content, token_est, "
    "embedding_ver) VALUES (?,?,?,?,?,?,NULL)"
)
_NOTE_SQL = (
    "INSERT INTO vault_note (path, title, mtime, size, content_hash, indexed_at, "
    "status) VALUES (?,?,?,?,?,?,?)"
)


def generate_vault(ctx: Ctx) -> None:
    p, rng = ctx.profile, ctx.rng
    base, extra = divmod(p.vault_chunks, p.notes)
    notes, chunks = [], []
    for index, moment in enumerate(ctx.timeline(p.notes)):
        folder = rng.choice(ctx.vocab.domain_words)
        slug = ctx.vocab.title(rng).replace(" ", "-").lower()
        path = f"notes/{folder}/{slug}-{index}.md"
        ctx.note_paths.append(path)
        texts = [
            chunk_text(ctx.vocab, rng)
            for _ in range(base + (1 if index < extra else 0))
        ]
        digest = hashlib.sha256("".join(texts).encode()).hexdigest()
        for seq, text in enumerate(texts, start=1):
            anchor = f"section-{seq}" if rng.random() < 0.8 else None
            chunks.append(
                (ctx.new_id(moment), path, anchor, seq, text, estimate_tokens(text))
            )
        notes.append(
            (
                path,
                ctx.vocab.title(rng),
                iso(moment),
                sum(len(t) for t in texts),
                digest,
                iso(later(moment, 60)),
                _NOTE_STATUS.pick(rng),
            )
        )
        if len(notes) == _NOTES_PER_GROUP:
            _flush_notes(ctx, notes, chunks)
            notes, chunks = [], []
    if notes:
        _flush_notes(ctx, notes, chunks)


def _flush_notes(ctx: Ctx, notes: list, chunks: list) -> None:
    statements = [(_NOTE_SQL, notes)]
    for start in range(0, len(chunks), CHUNK_ROWS):
        statements.append((_CHUNK_SQL, chunks[start : start + CHUNK_ROWS]))
    ctx.flush(statements)


def _source_detail(ctx: Ctx, kind: str, moment) -> str:
    rng = ctx.rng
    if kind == "web":
        return f"https://example.org/{rng.choice(ctx.vocab.domain_words)}/{rng.randrange(100000)}"
    if kind == "vault":
        return f"{rng.choice(ctx.note_paths)}#section-{rng.randint(1, 8)}"
    if kind == "rule":
        return f"rule:{rng.choice(ctx.vocab.domain_words)}-{rng.randint(1, 20)}"
    return ctx.new_id(moment)  # an invocation id


_CREATED_BY = {
    "stated": "kang",
    "web": "agent:researcher",
    "vault": "agent:vault_indexer",
    "consolidation": "agent:memory_steward",
}

_RECORD_SQL = (
    "INSERT INTO memory_record (id, type, status, content, trust_tier, confidence, "
    "sensitivity, content_enc, source_kind, source_detail, source_quote, reason, "
    "created_by, created_at, updated_at, device_id, revision, importance, pinned, "
    "last_accessed, access_count, embedding_ver) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)"
)


def generate_memory(ctx: Ctx) -> None:
    moments = list(ctx.timeline(ctx.profile.memory_records))
    records = [_record(ctx, moment) for moment in moments]
    _repair_statuses(records)
    revision_rows = _apply_revisions(ctx, records, moments)
    for rec in records:
        ctx.memory_ids.append(rec[0])
        ctx.memory_types.append(rec[1])
        ctx.memory_statuses.append(rec[2])
    ctx.write(_RECORD_SQL, records)
    ctx.write(_REVISION_SQL, revision_rows)
    _queue(ctx)


def _record(ctx: Ctx, moment) -> tuple:
    rng, vocab = ctx.rng, ctx.vocab
    mtype = _TYPE.pick(rng)
    tier = _TRUST[mtype].pick(rng)
    kind = _SOURCE[tier].pick(rng)
    sensitivity = _SENSITIVITY.pick(rng)
    if sensitivity == "private":
        content, enc = "[encrypted]", rng.randbytes(64)
    else:
        content, enc = vocab.sentences(rng, rng.randint(1, 3)), None
    at = iso(moment)
    accessed = rng.random() < 0.3
    return (
        ctx.new_id(moment),
        mtype,
        _STATUS.pick(rng),
        content,
        tier,
        round(rng.uniform(0.3, 0.7) if tier == 0 else rng.uniform(0.7, 1.0), 2),
        sensitivity,
        enc,
        kind,
        _source_detail(ctx, kind, moment),
        vocab.sentence(rng) if kind == "stated" and rng.random() < 0.5 else None,
        vocab.sentence(rng),
        _CREATED_BY.get(
            kind, f"rule:{rng.choice(vocab.domain_words)}-{rng.randint(1, 20)}"
        ),
        at,
        at,
        ctx.device(),
        1,
        round(rng.random(), 2),
        1 if mtype in ("rule", "profile") and rng.random() < 0.5 else 0,
        iso(later(moment, rng.randint(1, 400) * 86400)) if accessed else None,
        rng.randint(1, 40) if accessed else 0,
    )


def _repair_statuses(records: list[tuple]) -> None:
    """A `superseded` record needs an `active` record of the same type to be
    superseded by (06 §9.1); with none available, it stays `active`."""
    active_types = {r[1] for r in records if r[2] == "active"}
    for i, rec in enumerate(records):
        if rec[2] == "superseded" and rec[1] not in active_types:
            records[i] = (rec[0], rec[1], "active", *rec[3:])


_REVISION_SQL = (
    "INSERT INTO memory_revision (record_id, revision, content, edited_by, "
    "edited_at, device_id) VALUES (?,?,?,?,?,?)"
)


def _apply_revisions(ctx: Ctx, records: list[tuple], moments: list) -> list[tuple]:
    """Edited records: the prior content goes to memory_revision (06 §8.2) and
    the record becomes revision 2 by the editing device. Private records are
    never edited here — their plaintext must not exist in the database
    (DB-005). Patches `records` in place; they are not yet inserted."""
    rng = ctx.rng
    candidates = [i for i, r in enumerate(records) if r[6] != "private"]
    picked = rng.sample(candidates, min(ctx.profile.revisions, len(candidates)))
    revision_rows = []
    for i in sorted(picked):
        rec = list(records[i])
        edited_at = iso(later(moments[i], rng.randint(1, 200) * 86400))
        device = ctx.device()
        revision_rows.append((rec[0], 1, rec[3], "kang", edited_at, device))
        rec[3] = ctx.vocab.sentences(rng, rng.randint(1, 3))
        rec[14], rec[15], rec[16] = edited_at, device, 2
        records[i] = tuple(rec)
    return revision_rows


_QUEUE_SQL = (
    "INSERT INTO memory_candidate_queue (id, payload, flags, flag_context, "
    "proposed_at, expires_at, resolved, resolved_at) VALUES (?,?,?,?,?,?,?,?)"
)
_AI_TYPES = ("fact", "preference", "lesson", "observation")  # 06 §4.1


def _queue(ctx: Ctx) -> None:
    rng, vocab = ctx.rng, ctx.vocab
    rows = []
    for moment in ctx.timeline(ctx.profile.queue_rows):
        expires = later(moment, 14 * 86400)  # 07 §5.1: +14d
        payload = json.dumps(
            {
                "type": rng.choice(_AI_TYPES),
                "content": vocab.sentences(rng, rng.randint(1, 2)),
                "reason": vocab.sentence(rng),
                "source_kind": "observed",
            },
            sort_keys=True,
        )
        flags = _QUEUE_FLAGS.pick(rng)
        context = json.dumps([rng.choice(ctx.memory_ids)]) if flags != "[]" else None
        resolved = _QUEUE_RESOLVED.pick(rng)
        if resolved is None:
            resolved_at = None
        elif resolved == "expired":
            resolved_at = iso(expires)
        else:
            resolved_at = iso(later(moment, rng.randint(1, 10) * 86400))
        rows.append(
            (
                ctx.new_id(moment),
                payload,
                flags,
                context,
                iso(moment),
                iso(expires),
                resolved,
                resolved_at,
            )
        )
    ctx.write(_QUEUE_SQL, rows)


_EPISODE_SQL = (
    "INSERT INTO episode (id, type, occurred_at, content, summary, status, "
    "compressed_into, source_kind, source_detail, reason, created_by, created_at, "
    "updated_at, device_id, revision, embedding_ver) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)"
)
# type -> (source_kind, created_by); source_detail is a rule id or invocation id
_EPISODE_PROVENANCE = {
    "plan": ("rule", "rule:planner"),
    "review": ("stated", "kang"),
    "retrospective": ("rule", "rule:project_service"),
    "session": ("rule", "rule:learning_service"),
    "decision": ("stated", "kang"),
}


def generate_episodes(ctx: Ctx) -> None:
    rng, vocab = ctx.rng, ctx.vocab
    reviews: list[str] = []
    rows = []
    for moment in ctx.timeline(ctx.profile.episodes):
        eid = ctx.new_id(moment)
        etype = _EPISODE_TYPE.pick(rng)
        status = _EPISODE_STATUS.pick(rng)
        into = None
        if status == "compressed":
            if reviews:
                into = rng.choice(reviews)
            else:
                status = "archived"
        kind, by = _EPISODE_PROVENANCE[etype]
        detail = by if kind == "rule" else ctx.new_id(moment)
        at = iso(moment)
        body = json.dumps(
            {"kind": etype, "body": vocab.sentences(rng, rng.randint(2, 5))}
        )
        rows.append(
            (
                eid,
                etype,
                at,
                body,
                vocab.sentence(rng) if rng.random() < 0.9 else None,
                status,
                into,
                kind,
                detail,
                vocab.sentence(rng),
                by,
                at,
                at,
                ctx.device(),
                1,
            )
        )
        ctx.episode_ids.append(eid)
        if etype == "review":
            reviews.append(eid)
    ctx.write(_EPISODE_SQL, rows)
