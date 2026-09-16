"""`chat.send` handler (ADR-044, ADR-046) — the thin glue only. The
real cognitive-agent/turn run is injected as a plain `ChatRun`
callable; this test proves the handler reads `message`/`context_chips`/
`conversation_id` from params, returns the callable's own response
verbatim, and converts `ConversationNotFound` to `invalid_request`.
"""

from __future__ import annotations

import pytest

from kang.api.dispatch import HandlerContext
from kang.api.errors import ApiError
from kang.api.operations import make_chat_send_handler
from kang.domain.ports.conversation_store import ConversationNotFound

CONTEXT = HandlerContext(
    principal="kang", correlation_id="corr-1", trigger="cli", first_party=True
)


def test_handler_passes_message_chips_and_conversation_id_through_verbatim():
    calls = []

    def chat(message, context_chips, conversation_id) -> dict:
        calls.append((message, context_chips, conversation_id))
        return {"reply": "a reply", "degraded": False, "conversation_id": "conv-1"}

    handler = make_chat_send_handler(chat)
    response = handler(
        CONTEXT,
        {"message": "hi", "context_chips": ["a", "b"], "conversation_id": "conv-1"},
    )

    assert calls == [("hi", ["a", "b"], "conv-1")]
    assert response == {
        "reply": "a reply", "degraded": False, "conversation_id": "conv-1",
    }


def test_handler_defaults_missing_chips_and_conversation_id():
    calls = []

    def chat(message, context_chips, conversation_id) -> dict:
        calls.append((message, context_chips, conversation_id))
        return {"reply": "ok", "degraded": False, "conversation_id": "conv-new"}

    handler = make_chat_send_handler(chat)
    handler(CONTEXT, {"message": "hi"})

    assert calls == [("hi", [], None)]


def test_handler_returns_the_chat_run_response_exactly_including_degraded():
    def chat(message, context_chips, conversation_id) -> dict:
        return {"reply": "unavailable", "degraded": True, "conversation_id": "conv-1"}

    handler = make_chat_send_handler(chat)
    response = handler(CONTEXT, {"message": "hi", "context_chips": []})

    assert response == {
        "reply": "unavailable", "degraded": True, "conversation_id": "conv-1",
    }


def test_handler_converts_conversation_not_found_to_invalid_request():
    def chat(message, context_chips, conversation_id) -> dict:
        raise ConversationNotFound(f"no conversation {conversation_id!r}")

    handler = make_chat_send_handler(chat)
    with pytest.raises(ApiError) as exc_info:
        handler(CONTEXT, {"message": "hi", "conversation_id": "ghost"})

    assert exc_info.value.code == "invalid_request"
