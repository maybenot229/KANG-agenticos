"""`chat.send` handler (ADR-044) — the thin glue only. The real
cognitive-agent run is injected as a plain `ChatRun` callable; this
test proves the handler reads `message`/`context_chips` from params
and returns the callable's own response verbatim, nothing more.
"""

from __future__ import annotations

from kang.api.dispatch import HandlerContext
from kang.api.operations import make_chat_send_handler

CONTEXT = HandlerContext(
    principal="kang", correlation_id="corr-1", trigger="cli", first_party=True
)


def test_handler_passes_message_and_chips_through_verbatim():
    calls = []

    def chat(message: str, context_chips: list[str]) -> dict:
        calls.append((message, context_chips))
        return {"reply": "a reply", "degraded": False}

    handler = make_chat_send_handler(chat)
    response = handler(CONTEXT, {"message": "hi", "context_chips": ["a", "b"]})

    assert calls == [("hi", ["a", "b"])]
    assert response == {"reply": "a reply", "degraded": False}


def test_handler_defaults_missing_chips_to_empty_list():
    calls = []

    def chat(message: str, context_chips: list[str]) -> dict:
        calls.append((message, context_chips))
        return {"reply": "ok", "degraded": False}

    handler = make_chat_send_handler(chat)
    handler(CONTEXT, {"message": "hi"})

    assert calls == [("hi", [])]


def test_handler_returns_the_chat_run_response_exactly_including_degraded():
    def chat(message: str, context_chips: list[str]) -> dict:
        return {"reply": "unavailable", "degraded": True}

    handler = make_chat_send_handler(chat)
    response = handler(CONTEXT, {"message": "hi", "context_chips": []})

    assert response == {"reply": "unavailable", "degraded": True}
