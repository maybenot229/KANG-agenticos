"""memory.embed's handler (ADR-055 D7): it runs one bounded pass and audits
exactly what must be audited — a model/dimension mismatch and a cutover —
and returns the degraded marker rather than an empty success."""

from __future__ import annotations

from kang.adapters.fakes.audit_log import FakeAuditLog
from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.embedding_index import FakeEmbeddingIndex
from kang.adapters.fakes.memory_store import FakeMemoryStore
from kang.adapters.fakes.model_provider import FakeModelCallStore, FakeModelProvider
from kang.api.dispatch import HandlerContext
from kang.api.operations import MemoryEmbedDeps, make_memory_embed_handler
from kang.domain.ports.embedding_index import EmbeddingVersion
from kang.domain.ports.model_provider import ProviderUnavailable
from kang.domain.ports.provider_config import ProviderEntry, ProvidersConfig
from kang.kernel.audit.service import AuditService
from kang.kernel.router.router import Router
from tests.fixtures.memory_store_contract import record

CTX = HandlerContext(
    principal="kernel:scheduler",
    correlation_id="corr-1",
    trigger="schedule",
    first_party=False,
)


class Harness:
    def __init__(self, model: str = "nomic-embed-text") -> None:
        clock = FakeClock()
        self.memory = FakeMemoryStore()
        self.index = FakeEmbeddingIndex(self.memory)
        self.provider = FakeModelProvider()
        self.log = FakeAuditLog()
        router = Router(
            ProvidersConfig(
                chains={"embedding": (ProviderEntry("ollama", model, local_only=True),)}
            ),
            {"ollama": self.provider},
            FakeModelCallStore(),
            clock,
        )
        self.handler = make_memory_embed_handler(
            MemoryEmbedDeps(self.index, router.embed, AuditService(self.log, clock))
        )

    def actions(self) -> list[str]:
        return [r.entry.action for m in self.log.months() for r in self.log.records(m)]


def test_a_routine_pass_embeds_and_audits_nothing():
    h = Harness()
    h.memory.insert_record(record())
    response = h.handler(CTX, {})
    assert response == {
        "embedded": 1,
        "skipped_stale": 0,
        "cut_over": [],
        "unserved": [],
        "degraded": None,
        "mismatch": None,
    }
    assert h.actions() == []


def test_a_mismatch_is_audited_and_nothing_is_stored():
    h = Harness()
    h.memory.insert_record(record())
    h.provider.embed_echo_model = "wrong-model"
    assert h.handler(CTX, {})["mismatch"] is not None
    assert h.actions() == ["memory.embed.mismatch"]
    assert h.index.memory_coverage(1).embedded == 0


def test_a_cutover_is_audited():
    h = Harness(model="next-model")
    h.memory.insert_record(record())
    h.index.add_version(EmbeddingVersion(2, "next-model", 768, "migrating"))
    assert h.handler(CTX, {})["cut_over"] == [2]
    assert h.actions() == ["memory.embed.cutover"]


def test_a_degraded_pass_returns_its_marker():
    h = Harness()
    h.memory.insert_record(record())
    h.provider.embed_errors.append(ProviderUnavailable("closed"))
    assert h.handler(CTX, {})["degraded"] == "provider_unavailable"
