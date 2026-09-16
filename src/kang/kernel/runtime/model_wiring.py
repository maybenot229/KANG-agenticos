"""Model-call wiring — the composition root's Router/chat-specific slice
(ADR-044, ADR-046).

Layer: kernel/runtime, exempt from the import matrix exactly as
`composition.py`/`scheduler_wiring.py` are (17 §4.3's composition-root
exception) — registered by name in `tools/importlinter.toml`, one more
file in the same conceptual composition root, not a fourth role.

Split out of `composition.py` when this ADR's own Router/chat wiring
pushed that file past the size lint's hard limits — a mechanical
reason, not a new concept, the same trigger ADR-023/ADR-037 already
used for their own splits.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from kang.adapters.anthropic.provider import AnthropicProvider
from kang.adapters.config.providers_loader import ProvidersLoadError, load_providers
from kang.adapters.os_windows.credentials import KeyringCredentialStore
from kang.adapters.sqlite.model_call_store import SqliteModelCallStore
from kang.agents.runtime.executor import (
    ChatTurnDeps,
    CognitiveExecutorDeps,
    run_chat_turn,
)
from kang.domain.ports.conversation_store import ConversationStore
from kang.domain.ports.provider_config import ProvidersConfig
from kang.kernel.orchestrator.registry import AgentRegistry
from kang.kernel.router.router import Router

__all__ = ["ChatRun", "ChatWiringDeps", "build_router", "make_chat_run"]

# (message, context_chips, conversation_id) -> {"reply": str,
# "degraded": bool, "conversation_id": str}, verbatim — mirrors
# `api/operations/chat_ops.py`'s own ChatRun alias exactly (that module
# may not import this one, api -> agents/kernel both being forbidden —
# 17 §4.3.8); the composition root is the one place both shapes are
# known to agree. May raise ConversationNotFound (domain.ports) for an
# unknown client-supplied conversation_id — chat_ops.py's own handler
# catches it.
ChatRun = Callable[[str, list[str], str | None], dict]


def build_router(kang_home: Path, kang, clock) -> Router:
    """ADR-044: the first real wiring of the Model Router into a running
    `Core`. Fail-OPEN, not fail-closed — deliberately the opposite of
    `composition.py::_build_agent_registry`'s own posture:
    `providers.toml` is a live, hand-editable, `%KANG_HOME%`-scoped file
    (D003) Kang might genuinely edit or typo, and ADR-038 D5 already
    decided its OWN fail-closed shape for the Router's own routing
    decisions (an absent/invalid file yields the empty `ProvidersConfig`,
    routing everything to nothing) — reused verbatim here rather than
    bricking boot over it, the same `_load_grants`-style reasoning for a
    hand-edited config file. Constructing `KeyringCredentialStore`/
    `AnthropicProvider` never touches the network or the keychain itself
    (both read lazily, inside `.call()`) — safe to always build,
    credential or not."""
    try:
        config = load_providers(kang_home / "config" / "providers.toml")
    except ProvidersLoadError:
        config = ProvidersConfig()
    providers = {"anthropic": AnthropicProvider(KeyringCredentialStore())}
    return Router(config, providers, SqliteModelCallStore(kang), clock)


@dataclass(frozen=True)
class ChatWiringDeps:
    """Everything `make_chat_run` needs (11 §4: beyond a few params, a
    dataclass — this crossed that line the moment ADR-046 added
    `conversations`)."""

    agent_definitions_dir: Path
    agent_registry: AgentRegistry
    router: Router
    conversations: ConversationStore
    sessions: object
    new_id: object
    clock: object


def make_chat_run(wiring: ChatWiringDeps) -> ChatRun:
    """Builds the plain `ChatRun` callable `chat_ops.make_chat_send_handler`
    needs (ADR-044/046) — `api` may not import `kang.agents`, so this
    closure, not the handler itself, is where `run_chat_turn` is
    actually called. Reads the real `chat` `AgentDefinition` from the
    registry on every call (never cached) — the same "always the
    current, validated definition" posture every other registry lookup
    in this codebase already has."""

    def read_prompt(agent) -> str:
        path = wiring.agent_definitions_dir / agent.id / agent.prompt_file
        return path.read_text(encoding="utf-8")

    deps = ChatTurnDeps(
        cognitive=CognitiveExecutorDeps(
            route=wiring.router.route,
            read_prompt=read_prompt,
            sessions=wiring.sessions,
            new_id=wiring.new_id,
            clock=wiring.clock,
        ),
        conversations=wiring.conversations,
    )

    def chat_run(
        message: str, context_chips: list[str], conversation_id: str | None
    ) -> dict:
        agent = wiring.agent_registry.get("chat")
        if agent is None:
            raise KeyError(
                "chat.send was registered but no 'chat' agent exists in "
                "the AgentRegistry — a wiring defect, not a runtime "
                "condition to degrade past"
            )
        return run_chat_turn(agent, message, context_chips, conversation_id, deps)

    return chat_run
