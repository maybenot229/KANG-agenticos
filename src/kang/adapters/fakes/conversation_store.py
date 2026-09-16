"""FakeConversationStore — in-memory ConversationStore, contract-paired
(13 §2.3).

Layer: adapters/fakes.
Constitutional home: 11_CODING §5/§7 (every port has an in-memory fake).
A fake that lies is a red build (13 §2.3): the same contract suite runs
against this and `SqliteConversationStore`.
"""

from __future__ import annotations

from dataclasses import replace

from kang.domain.ports.conversation_store import (
    Conversation,
    ConversationNotFound,
    Message,
)

__all__ = ["FakeConversationStore"]


class FakeConversationStore:
    """ConversationStore over two dicts, mirroring the real adapter's
    own append-bumps-count-and-last_message behavior exactly."""

    def __init__(self) -> None:
        self._conversations: dict[str, Conversation] = {}
        self._messages: dict[str, list[Message]] = {}

    def start(self, conversation_id: str, started_at: str) -> Conversation:
        conversation = Conversation(
            id=conversation_id, started=started_at, last_message=started_at,
            title=None, message_count=0, purged=False,
        )
        self._conversations[conversation_id] = conversation
        self._messages[conversation_id] = []
        return conversation

    def get(self, conversation_id: str) -> Conversation | None:
        return self._conversations.get(conversation_id)

    def append_message(
        self, conversation_id: str, message_id: str, role: str, content: str, at: str
    ) -> Message:
        conversation = self._conversations.get(conversation_id)
        if conversation is None:
            raise ConversationNotFound(
                f"no conversation {conversation_id!r} to append a message to"
            )
        message = Message(
            id=message_id, conversation_id=conversation_id, role=role,
            content=content, at=at,
        )
        self._messages[conversation_id].append(message)
        self._conversations[conversation_id] = replace(
            conversation, last_message=at, message_count=conversation.message_count + 1,
        )
        return message

    def recent_messages(self, conversation_id: str, limit: int) -> tuple[Message, ...]:
        messages = self._messages.get(conversation_id, [])
        return tuple(messages[-limit:]) if limit > 0 else ()
