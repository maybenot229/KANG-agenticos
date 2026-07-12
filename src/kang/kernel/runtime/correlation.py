"""Correlation-id context — one id threading click → invocation → audit.

Layer: kernel/runtime (machinery; no domain knowledge).
Constitutional home: 12_API §5 (correlation_id minted at ingress, returned on
every response, threads audit/invocation/explain — one id, end to end,
forever); 04_ARCHITECTURE D015. Minting happens at the API ingress (M4);
this module owns the propagation context everything else reads.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

__all__ = ["correlation_context", "get_correlation_id"]

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> str | None:
    """The correlation id bound to the current execution context, if any."""
    return _correlation_id.get()


@contextmanager
def correlation_context(correlation_id: str) -> Iterator[None]:
    """Bind a correlation id for the duration of an ingress-scoped block."""
    token = _correlation_id.set(correlation_id)
    try:
        yield
    finally:
        _correlation_id.reset(token)
