"""memory.embed — the embedding worker's API surface (ADR-055 D7).

Layer: api. The handler runs one bounded pass of the domain policy
(`domain/memory/embedding.py`) and audits what the audit log must hold;
no embedding policy lives here.
Constitutional home: 07_DATABASE §6.2 (the embedding worker), DB-004 (never
mix model spaces; cutover at full coverage), A9 (a missing provider is a
declared degraded state), ADR-055 D6-D8.

Audited: a mismatch (the served model or dimension fit no version — nothing
was stored) and every cutover (a version becoming the one retrieval reads).
Not audited: routine passes — vectors are derived data (07 Appendix A), and a
five-minute job would drown the log. A degraded pass is logged as a warning
and returned with its marker.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from kang.api.dispatch import Handler, HandlerContext
from kang.domain.memory.embedding import Embed, run_embedding_pass
from kang.domain.ports.embedding_index import EmbeddingIndex
from kang.kernel.audit.service import AuditService

__all__ = ["MemoryEmbedDeps", "make_memory_embed_handler"]

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemoryEmbedDeps:
    index: EmbeddingIndex
    embed: Embed  # Router.embed, bound at the composition root
    audit: AuditService


def make_memory_embed_handler(deps: MemoryEmbedDeps) -> Handler:
    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        result = run_embedding_pass(deps.index, deps.embed)
        if result.mismatch is not None:
            deps.audit.record(
                context.principal,
                "memory.embed.mismatch",
                {"detail": result.mismatch},
                correlation_id=context.correlation_id,
            )
        for ver in result.cut_over:
            deps.audit.record(
                context.principal,
                "memory.embed.cutover",
                {"ver": ver},
                correlation_id=context.correlation_id,
            )
        if result.degraded is not None:
            _logger.warning(
                "embedding pass degraded", extra={"degraded": result.degraded}
            )
        return {
            "embedded": result.embedded,
            "skipped_stale": result.skipped_stale,
            "cut_over": list(result.cut_over),
            "unserved": list(result.unserved),
            "degraded": result.degraded,
            "mismatch": result.mismatch,
        }

    return handler
