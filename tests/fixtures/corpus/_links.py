"""Links and the derived `link_index` (ADR-049 D2/D3).

Invariants the generator keeps (and its own tests assert): every `superseded`
record has a `superseded_by`/`supersedes` pair with an `active` record of the
same type; every `lesson` has >=1 `derived_from` to a real episode;
`about_*`/`references_note`/`from_conversation` endpoints are real ids/paths
(06 §9.1). `link_index` mirrors every `link` row (`origin='link'`) plus the
FK columns of the structured store (`origin='fk'`: task/milestone/deadline/
competition -> project or competition, project -> goal) — the corpus is
honest that it *simulates* the state the indexer will derive.
"""

from __future__ import annotations

from ._ctx import CHUNK_ROWS, Ctx, Weighted, iso
from .profiles import FILLER_LINKS, LINK_STATUSES

_FILLER = Weighted(FILLER_LINKS)
_STATUS = Weighted(LINK_STATUSES)
_CREATED_BY = ("kang", "rule:consolidator", "agent:memory_steward")

_LINK_SQL = (
    "INSERT INTO link (id, src_kind, src_id, dst_kind, dst_id, type, status, "
    "created_by, created_at, reason, device_id, revision) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,1)"
)
_INDEX_SQL = "INSERT INTO link_index (src, dst, type, origin) VALUES (?,?,?,?)"

Edge = tuple[str, str, str, str, str]  # src_kind, src_id, dst_kind, dst_id, type


def _mandatory(ctx: Ctx, seen: set[Edge]) -> list[Edge]:
    rng = ctx.rng
    active: dict[str, list[str]] = {}
    for mid, mtype, status in zip(
        ctx.memory_ids, ctx.memory_types, ctx.memory_statuses
    ):
        if status == "active":
            active.setdefault(mtype, []).append(mid)
    edges: list[Edge] = []

    def add(edge: Edge) -> None:
        if edge not in seen:
            seen.add(edge)
            edges.append(edge)

    for mid, mtype, status in zip(
        ctx.memory_ids, ctx.memory_types, ctx.memory_statuses
    ):
        if status == "superseded":
            successor = rng.choice(active[mtype])
            add(("memory", mid, "memory", successor, "superseded_by"))
            add(("memory", successor, "memory", mid, "supersedes"))
        elif status == "under_review" and mtype in active:
            other = rng.choice(active[mtype])
            add(("memory", mid, "memory", other, "contradicts"))
        if mtype == "lesson" and ctx.episode_ids:
            for _ in range(rng.randint(1, 2)):
                add(
                    (
                        "memory",
                        mid,
                        "episode",
                        rng.choice(ctx.episode_ids),
                        "derived_from",
                    )
                )
    return edges


def _filler_edge(ctx: Ctx, lessons: list[str], people: list[str]) -> Edge:
    rng = ctx.rng
    ltype = _FILLER.pick(rng)
    src_kind = "memory" if rng.random() < 0.7 else "episode"
    src_id = rng.choice(ctx.memory_ids if src_kind == "memory" else ctx.episode_ids)
    if ltype == "about_project":
        return (src_kind, src_id, "project", rng.choice(ctx.project_ids), ltype)
    if ltype == "about_competition":
        return (src_kind, src_id, "competition", rng.choice(ctx.competition_ids), ltype)
    if ltype == "about_goal":
        return (src_kind, src_id, "goal", rng.choice(ctx.goal_ids), ltype)
    if ltype == "references_note":
        return (
            "memory",
            rng.choice(ctx.memory_ids),
            "note",
            rng.choice(ctx.note_paths),
            ltype,
        )
    if ltype == "from_conversation":
        return (
            "memory",
            rng.choice(ctx.memory_ids),
            "conversation",
            rng.choice(ctx.conversation_ids),
            ltype,
        )
    if ltype == "about_person" and people:
        return (
            "memory",
            rng.choice(ctx.memory_ids),
            "memory",
            rng.choice(people),
            ltype,
        )
    if ltype in ("evidence_for", "evidence_against") and lessons:
        return (
            "memory",
            rng.choice(ctx.memory_ids),
            "memory",
            rng.choice(lessons),
            ltype,
        )
    dst_kind = "memory" if rng.random() < 0.7 else "episode"
    dst_id = rng.choice(ctx.memory_ids if dst_kind == "memory" else ctx.episode_ids)
    return (src_kind, src_id, dst_kind, dst_id, "relates_to")


def generate_links(ctx: Ctx) -> None:
    target = ctx.profile.links
    seen: set[Edge] = set()
    edges = _mandatory(ctx, seen)
    mandatory = len(edges)
    lessons = [m for m, t in zip(ctx.memory_ids, ctx.memory_types) if t == "lesson"]
    people = [
        m for m, t in zip(ctx.memory_ids, ctx.memory_types) if t == "relationship"
    ]
    attempts = 0
    while len(edges) < target and attempts < target * 20:
        attempts += 1
        edge = _filler_edge(ctx, lessons, people)
        if edge[:2] == edge[2:4] or edge in seen:
            continue
        seen.add(edge)
        edges.append(edge)
    _write(ctx, edges, mandatory)


def _write(ctx: Ctx, edges: list[Edge], mandatory: int) -> None:
    rng = ctx.rng
    links, index = [], []
    for position, (moment, edge) in enumerate(zip(ctx.timeline(len(edges)), edges)):
        sk, sid, dk, did, ltype = edge
        status = "active" if position < mandatory else _STATUS.pick(rng)
        links.append(
            (
                ctx.new_id(moment),
                sk,
                sid,
                dk,
                did,
                ltype,
                status,
                rng.choice(_CREATED_BY),
                iso(moment),
                ctx.vocab.sentence(rng) if rng.random() < 0.5 else None,
                ctx.device(),
            )
        )
        index.append((f"{sk}:{sid}", f"{dk}:{did}", ltype, "link"))
        if len(links) == CHUNK_ROWS:
            ctx.flush([(_LINK_SQL, links), (_INDEX_SQL, index)])
            links, index = [], []
    if links:
        ctx.flush([(_LINK_SQL, links), (_INDEX_SQL, index)])
    fk_rows = [(src, dst, ltype, "fk") for src, dst, ltype in ctx.fk_edges]
    ctx.write(_INDEX_SQL, fk_rows)
