"""`chat.send` handler — the Chat domain's own first operation (ADR-044,
ADR-046).

Layer: api.
Constitutional home: 12_API §2 (handlers contain dispatch-to-domain
only), ADR-044 D3, ADR-046 D4.

`api` may not import `kang.agents` (17 §4.3.8) — the actual cognitive-
agent run (`agents.runtime.executor::run_chat_turn`) happens at the
composition root, which injects a plain, generic `ChatRun` callable
here instead, exactly the shape `agents/runtime/executor.py`'s own
`Dispatch`/`RouterRoute` already use to stay ignorant of what's on the
other side of a layer boundary. `ConversationNotFound` is a domain
port exception (`kang.domain.ports.conversation_store`), which `api`
MAY import (only `kang.agents`/`adapters`/`plugins_sdk` are forbidden)
— caught here and converted to `invalid_request`, the one place this
handler needs to know anything beyond "call this function."
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from kang.api.dispatch import Handler, HandlerContext
from kang.api.errors import ApiError
from kang.domain.ports.conversation_store import ConversationNotFound

__all__ = ["ChatRun", "make_chat_send_handler"]

# (message, context_chips, conversation_id) -> {"reply": str,
# "degraded": bool, "conversation_id": str}, verbatim — the composition
# root's own closure over a real AgentDefinition, ChatTurnDeps, and
# run_chat_turn. May raise ConversationNotFound for an unknown
# client-supplied conversation_id.
ChatRun = Callable[[str, list[str], str | None], dict[str, Any]]


def make_chat_send_handler(chat: ChatRun) -> Handler:
    """`chat.send` (ADR-044 D3): one conversational turn, blocking for
    the chat agent's own `timeout_s` — a narrow, documented exception to
    API-007 (ADR-044 D6), never an invocation-resource/streaming shape."""

    def handler(context: HandlerContext, params: dict[str, Any]) -> dict[str, Any]:
        message = params.get("message", "")
        context_chips = params.get("context_chips", [])
        conversation_id = params.get("conversation_id")
        try:
            return chat(message, context_chips, conversation_id)
        except ConversationNotFound as exc:
            raise ApiError("invalid_request", str(exc)) from exc

    return handler
