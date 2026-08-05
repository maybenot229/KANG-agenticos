"""registry.get handler.

Layer: api.
Constitutional home: 12_API §16 (the registry is the contract, served
machine-readable).
"""

from __future__ import annotations

from typing import Any

from kang.api.dispatch import Handler, HandlerContext
from kang.api.registry import registry_snapshot

__all__ = ["make_registry_get_handler"]


def make_registry_get_handler() -> Handler:
    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        return registry_snapshot()

    return handler
