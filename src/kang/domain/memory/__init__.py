"""Write gate, lifecycle, scoring, taxonomy.

Layer: domain.
Constitutional home: 06_MEMORY (built at Phase 2 — 18 §4; M-003 lives here).
Built so far: the write gate (`write_gate`) and record construction
(`records`), ADR-051.
"""

from kang.domain.memory.records import (
    MEMORY_EVENT_FIELDS,
    build_record,
    candidate_to_proposal,
    memory_event_payload,
    merged_record,
    proposal_payload,
)
from kang.domain.memory.write_gate import (
    KANG,
    RESTRICTED_TYPES,
    GateDecision,
    GateProbes,
    Proposal,
    Writer,
    authorize_resolution,
    decide,
    validate_proposal,
)

__all__ = [
    "KANG",
    "MEMORY_EVENT_FIELDS",
    "RESTRICTED_TYPES",
    "GateDecision",
    "GateProbes",
    "Proposal",
    "Writer",
    "authorize_resolution",
    "build_record",
    "candidate_to_proposal",
    "decide",
    "memory_event_payload",
    "merged_record",
    "proposal_payload",
    "validate_proposal",
]
