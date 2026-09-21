"""The memory write gate — admission as pure policy (ADR-051 D4-D6, D10).

Layer: domain/memory (deterministic, zero I/O).
Constitutional home: 06_MEMORY Part IV (§4.1 the writers table, §4.2 the
pipeline and its required metadata), **M-003** (AI proposals never
auto-commit, at any confidence), ADR-051.

`decide()` takes a proposal, the *authenticated* writer, and the probe
results the caller gathered, and returns a typed `GateDecision`. There is no
configuration key, no threshold, and no argument that yields `admit` for
anyone but a first-party `kang` session — M-003 made structural. The
proposal's `confidence` is carried and stored; nothing here reads it.

The writer's identity is never a field of the proposal: it comes from the
session (`Writer`), so a caller cannot claim to be someone else.
"""

from __future__ import annotations

from dataclasses import dataclass

from kang.domain.ports.memory_store import (
    MEMORY_TYPES,
    SENSITIVITIES,
    SOURCE_KINDS,
    TRUST_TIERS,
)

__all__ = [
    "KANG",
    "RESTRICTED_TYPES",
    "GateDecision",
    "GateProbes",
    "Proposal",
    "Writer",
    "authorize_resolution",
    "decide",
    "validate_proposal",
]

KANG = "kang"
# 06 §4.1's hard prohibition: only Kang may write these (a model must never
# be able to instruct future-KANG or redefine Kang).
RESTRICTED_TYPES = ("rule", "profile")
_AGENT_PREFIX = "agent:"


@dataclass(frozen=True)
class Writer:
    """Who is writing, as authenticated by the session — never as claimed."""

    principal: str
    first_party: bool

    @property
    def is_kang(self) -> bool:
        """The one identity that auto-passes: principal exactly `kang` on a
        first-party session (D4)."""
        return self.principal == KANG and self.first_party


@dataclass(frozen=True)
class Proposal:
    """06 §4.2's required metadata, minus what the system stamps (id,
    created_by, created_at, device_id — set from the session and clock)."""

    type: str
    content: str
    trust_tier: int
    source_kind: str
    source_detail: str
    reason: str
    confidence: float = 1.0
    sensitivity: str = "normal"
    source_quote: str | None = None


@dataclass(frozen=True)
class GateProbes:
    """What the caller learned from the store. Today: the exact-hash probe
    only; cosine/NLI are ADR-051 D5's named absence."""

    exact_duplicate_id: str | None = None


@dataclass(frozen=True)
class GateDecision:
    """`outcome` is one of admit | queue | merge | reject. `code` names why a
    `reject` happened (stable, machine-readable); `reason` is one honest
    sentence."""

    outcome: str
    reason: str
    code: str | None = None
    merge_into: str | None = None


def _reject(code: str, reason: str) -> GateDecision:
    return GateDecision("reject", reason, code=code)


def validate_proposal(proposal: Proposal) -> str | None:
    """Schema/provenance validity (06 §4.2's first gate, §8.1: missing
    provenance is a violation, not a warning). Returns the first violation
    as a sentence, or None. Enforced here AND by the schema's CHECKs —
    defence in depth, deliberately."""
    if proposal.type not in MEMORY_TYPES:
        return f"type must be one of {MEMORY_TYPES}"
    if not proposal.content.strip():
        return "content must be non-empty"
    if proposal.trust_tier not in TRUST_TIERS:
        return f"trust_tier must be one of {TRUST_TIERS}"
    if proposal.source_kind not in SOURCE_KINDS:
        return f"source_kind must be one of {SOURCE_KINDS}"
    if not proposal.source_detail.strip():
        return "source_detail (provenance) must be non-empty"
    if not proposal.reason.strip():
        return "reason (why this is worth keeping) must be non-empty"
    if not 0.0 <= proposal.confidence <= 1.0:
        return "confidence must be within [0, 1]"
    if proposal.sensitivity not in SENSITIVITIES:
        return f"sensitivity must be one of {SENSITIVITIES}"
    return None


def decide(proposal: Proposal, writer: Writer, probes: GateProbes) -> GateDecision:
    """06 §4.2's pipeline, in order: valid -> writer accountable -> not
    `private` -> type permitted -> exact duplicate (merge) -> Kang admits,
    everyone else queues."""
    violation = validate_proposal(proposal)
    if violation is not None:
        return _reject("invalid", violation)
    principal = writer.principal
    if principal != KANG and not principal.startswith(_AGENT_PREFIX):
        # D6: `rule:`/`plugin:` writers (no registry / no plugin system yet)
        # and any principal shape the gate cannot hold to account.
        return _reject(
            "writer_refused",
            f"writer {principal!r} cannot be held to account yet "
            "(rule/plugin writers arrive with their slices)",
        )
    if proposal.sensitivity == "private":
        return _reject(
            "private_unsupported",
            "private records need the encryptor, which does not exist yet",
        )
    if proposal.type in RESTRICTED_TYPES and not writer.is_kang:
        return _reject(
            "type_restricted",
            f"only Kang may write {proposal.type!r} records (06 §4.1)",
        )
    if probes.exact_duplicate_id is not None:
        return GateDecision(
            "merge",
            "exact duplicate of an active record: provenance merged",
            merge_into=probes.exact_duplicate_id,
        )
    if writer.is_kang:
        return GateDecision("admit", "first-party Kang save auto-passes (06 §4.1)")
    return GateDecision("queue", "non-Kang proposal: queued for Kang (M-003)")


def authorize_resolution(writer: Writer) -> GateDecision | None:
    """Who may resolve the approval queue at all. Only first-party `kang`:
    a wrongly granted `memory.approve` scope on any other principal must
    still not be a second door to an active record. None means permitted."""
    if writer.is_kang:
        return None
    return _reject(
        "approval_restricted",
        "only a first-party Kang session may resolve the approval queue (M-003)",
    )
