"""memory.search's handler (ADR-056): request validation, the fail-closed
config, the sensitive-read audit (06 §12.3), and the response shape."""

from __future__ import annotations

import pytest

from kang.adapters.fakes.audit_log import FakeAuditLog
from kang.adapters.fakes.clock import FakeClock
from kang.adapters.fakes.embedding_index import FakeEmbeddingIndex
from kang.adapters.fakes.memory_search import FakeMemorySearchStore
from kang.adapters.fakes.memory_store import FakeMemoryStore
from kang.adapters.fakes.model_provider import FakeModelCallStore, FakeModelProvider
from kang.api.dispatch import HandlerContext
from kang.api.errors import ApiError
from kang.api.operations import MemorySearchDeps, make_memory_search_handler
from kang.api.schemas.memory import MemorySearchResponse
from kang.domain.ports.memory_config import ScoringConfig, ScoringWeights
from kang.domain.ports.memory_store import MEMORY_TYPES
from kang.domain.ports.provider_config import ProvidersConfig
from kang.kernel.audit.service import AuditService
from kang.kernel.router.router import Router
from tests.fixtures.memory_store_contract import record

CTX = HandlerContext(
    principal="kang", correlation_id="corr-1", trigger="ui", first_party=True
)
CONFIG = ScoringConfig(
    ScoringWeights(0.40, 0.20, 0.15, 0.15, 0.10),
    {t: 0.0 for t in MEMORY_TYPES},
    match_min_similarity=0.5,
)


class Harness:
    def __init__(self, config: ScoringConfig | None = CONFIG) -> None:
        clock = FakeClock()
        self.memory = FakeMemoryStore()
        self.log = FakeAuditLog()
        router = Router(  # no embedding chain: lexical only, degraded
            ProvidersConfig(),
            {"ollama": FakeModelProvider()},
            FakeModelCallStore(),
            clock,
        )
        self.handler = make_memory_search_handler(
            MemorySearchDeps(
                store=FakeMemorySearchStore(self.memory),
                index=FakeEmbeddingIndex(self.memory),
                embed=router.embed,
                audit=AuditService(self.log, clock),
                clock=clock,
                config=config,
            )
        )

    def actions(self) -> list:
        return [r.entry for m in self.log.months() for r in self.log.records(m)]


def test_the_response_validates_against_its_registry_schema():
    h = Harness()
    h.memory.insert_record(record(content="robotics team", pinned=True))
    response = h.handler(CTX, {"query": "robotics"})
    MemorySearchResponse.model_validate(response)
    (hit,) = response["results"]
    assert hit["id"] == "mem-1" and hit["terms"]["importance"] == 1.0
    assert response["degraded"] == "semantic_unavailable"


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"query": "   "},
        {"query": "x", "mode": "structured"},
        {"query": "x", "types": ["not-a-type"]},
        {"query": "x", "min_tier": 3},
    ],
)
def test_malformed_requests_are_invalid(params):
    with pytest.raises(ApiError) as caught:
        Harness().handler(CTX, params)
    assert caught.value.code == "invalid_request"


def test_a_missing_scoring_config_refuses_and_never_defaults():
    with pytest.raises(ApiError) as caught:
        Harness(config=None).handler(CTX, {"query": "robotics"})
    assert caught.value.code == "internal"


def test_returning_a_sensitive_record_is_audited_by_id_never_content():
    h = Harness()
    h.memory.insert_record(
        record(id="s", content="robotics grades", sensitivity="sensitive")
    )
    h.memory.insert_record(record(id="n", content="robotics team"))
    h.handler(CTX, {"query": "robotics"})
    (entry,) = h.actions()
    assert entry.action == "memory.read.sensitive"
    assert entry.details["ids"] == ["s"]
    assert "grades" not in repr(entry)


def test_normal_reads_are_not_audited():
    h = Harness()
    h.memory.insert_record(record(content="robotics team"))
    h.handler(CTX, {"query": "robotics"})
    assert h.actions() == []


def test_limit_is_clamped():
    h = Harness()
    for i in range(5):
        h.memory.insert_record(record(id=f"m{i}", content=f"robotics {i}"))
    assert len(h.handler(CTX, {"query": "robotics", "limit": 2})["results"]) == 2
    assert len(h.handler(CTX, {"query": "robotics", "limit": 0})["results"]) == 1
