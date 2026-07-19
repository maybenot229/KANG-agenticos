"""The one error model (API-006) — every failure, the same envelope.

Layer: api.
Constitutional home: 12_API API-006 (`{code, message, correlation_id,
retryable, details?, remedy?}`; `code` is a closed registry-published enum;
`message` is one honest sentence rendered verbatim by the UI, 09 §13).
`permission_denied` names the missing scope; `confirmation_required` returns
the held-action reference; `conflict` returns the current revision.
`first_party_required` (ADR 002 Amendment §3): the CHANNEL denial, distinct
from `permission_denied` — a capability grant cannot satisfy it. Name is
PROPOSED, not yet confirmed by Kang; flagged in-line until it is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["ERROR_CODES", "ApiError"]

# The closed error-code enum (API-006). Served in the registry (§16).
ERROR_CODES: tuple[str, ...] = (
    "invalid_request",
    "not_found",
    "conflict",
    "permission_denied",
    "first_party_required",  # PROPOSED name (ADR 002 Amendment) — pending
    "confirmation_required",
    "budget_exhausted",
    "degraded_result",
    "quarantined",
    "frozen",
    "timeout",
    "cancelled",
    "internal",
)

# Codes whose failures are safe to retry unchanged (API-006 `retryable`).
_RETRYABLE = frozenset({"timeout", "internal"})


@dataclass
class ApiError(Exception):
    """A failure in the one shape. Raised inside the API layer; the binding
    serializes it to the API-006 envelope with the correlation_id attached."""

    code: str
    message: str
    details: dict[str, Any] | None = None
    remedy: str | None = None

    def __post_init__(self) -> None:
        if self.code not in ERROR_CODES:
            raise ValueError(f"error code {self.code!r} is not in the closed enum")
        super().__init__(self.message)

    @property
    def retryable(self) -> bool:
        return self.code in _RETRYABLE

    def to_envelope(self, correlation_id: str) -> dict[str, Any]:
        envelope: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "correlation_id": correlation_id,
            "retryable": self.retryable,
        }
        if self.details is not None:
            envelope["details"] = self.details
        if self.remedy is not None:
            envelope["remedy"] = self.remedy
        return envelope
