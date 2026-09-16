"""`chat.send` handler — the Chat domain's own first operation (ADR-044).

Layer: api.
Constitutional home: 12_API §2 (handlers contain dispatch-to-domain
only), ADR-044 D3.

`api` may not import `kang.agents` (17 §4.3.8) — the actual cognitive-
agent run (`agents.runtime.executor::run_cognitive_agent`) happens at
the composition root, which injects a plain, generic `ChatRun` callable
here instead, exactly the shape `agents/runtime/executor.py`'s own
`Dispatch`/`RouterRoute` already use to stay ignorant of what's on the
other side of a layer boundary.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from kang.api.dispatch import Handler, HandlerContext

__all__ = ["ChatRun", "make_chat_send_handler"]

# (message, context_chips) -> {"reply": str, "degraded": bool}, verbatim
# — the composition root's own closure over a real AgentDefinition,
# CognitiveExecutorDeps, and run_cognitive_agent.
ChatRun = Callable[[str, list[str]], dict[str, Any]]


def make_chat_send_handler(chat: ChatRun) -> Handler:
    """`chat.send` (ADR-044 D3): one conversational turn, blocking for
    the chat agent's own `timeout_s` — a narrow, documented exception to
    API-007 (ADR-044 D6), never an invocation-resource/streaming shape."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        message = params.get("message", "")
        context_chips = params.get("context_chips", [])
        return chat(message, context_chips)

    return handler
