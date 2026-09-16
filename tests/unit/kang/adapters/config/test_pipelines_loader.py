"""Pipeline definition loader (AG-002, ADR-042): structural parsing and
validation only — the cross-registry check against a real AgentRegistry
lives in kernel/orchestrator/pipeline_registry.py's own test file, not
here (adapters may not import kernel).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kang.adapters.config.pipelines_loader import (
    discover_pipeline_definitions,
    parse_pipeline_definition,
)
from kang.domain.ports.pipeline_definition import PipelineDefinitionInvalid

REPO_ROOT = Path(__file__).resolve().parents[5]
SHIPPED_PIPELINES_DIR = REPO_ROOT / "src" / "kang" / "agents" / "pipelines"

_MINIMAL = """
id = "sample"

[[steps]]
agent_id = "scout"

[[steps]]
agent_id = "notifier"
mode = "digest"
"""


def _path(tmp_path: Path, name: str) -> Path:
    return tmp_path / f"{name}.toml"


def test_parses_a_minimal_pipeline():
    definition = parse_pipeline_definition(_MINIMAL, path=Path("sample.toml"))
    assert definition.id == "sample"
    assert len(definition.steps) == 2
    assert definition.steps[0].agent_id == "scout"
    assert definition.steps[0].mode is None
    assert definition.steps[1].agent_id == "notifier"
    assert definition.steps[1].mode == "digest"


def test_steps_are_ordered_not_reordered():
    text = """
id = "sample"

[[steps]]
agent_id = "c"

[[steps]]
agent_id = "a"

[[steps]]
agent_id = "b"
"""
    definition = parse_pipeline_definition(text, path=Path("sample.toml"))
    assert [s.agent_id for s in definition.steps] == ["c", "a", "b"]


def test_malformed_toml_raises():
    with pytest.raises(PipelineDefinitionInvalid, match="valid TOML"):
        parse_pipeline_definition("[steps\nbroken", path=Path("sample.toml"))


def test_missing_id_raises():
    text = _MINIMAL.replace('id = "sample"', "")
    with pytest.raises(PipelineDefinitionInvalid, match="'id'"):
        parse_pipeline_definition(text, path=Path("sample.toml"))


def test_id_not_matching_filename_stem_raises():
    with pytest.raises(PipelineDefinitionInvalid, match="does not match"):
        parse_pipeline_definition(_MINIMAL, path=Path("different.toml"))


def test_missing_steps_key_raises():
    steps_block = (
        '[[steps]]\nagent_id = "scout"\n\n'
        '[[steps]]\nagent_id = "notifier"\nmode = "digest"\n'
    )
    text = _MINIMAL.replace(steps_block, "")
    with pytest.raises(PipelineDefinitionInvalid, match="'steps'"):
        parse_pipeline_definition(text, path=Path("sample.toml"))


def test_empty_steps_list_raises():
    text = 'id = "sample"\nsteps = []\n'
    with pytest.raises(PipelineDefinitionInvalid, match="non-empty"):
        parse_pipeline_definition(text, path=Path("sample.toml"))


def test_step_missing_agent_id_raises():
    text = 'id = "sample"\n\n[[steps]]\nmode = "x"\n'
    with pytest.raises(PipelineDefinitionInvalid, match="agent_id"):
        parse_pipeline_definition(text, path=Path("sample.toml"))


def test_step_with_empty_agent_id_raises():
    text = 'id = "sample"\n\n[[steps]]\nagent_id = ""\n'
    with pytest.raises(PipelineDefinitionInvalid, match="agent_id"):
        parse_pipeline_definition(text, path=Path("sample.toml"))


def test_step_with_non_string_mode_raises():
    text = 'id = "sample"\n\n[[steps]]\nagent_id = "scout"\nmode = 5\n'
    with pytest.raises(PipelineDefinitionInvalid, match="mode"):
        parse_pipeline_definition(text, path=Path("sample.toml"))


def test_mode_is_captured_but_never_validated():
    # ADR-042 D3's own restraint: a nonsense mode string still loads.
    text = 'id = "sample"\n\n[[steps]]\nagent_id = "scout"\nmode = "not-a-real-facet"\n'
    definition = parse_pipeline_definition(text, path=Path("sample.toml"))
    assert definition.steps[0].mode == "not-a-real-facet"


def test_discover_walks_every_toml_file(tmp_path):
    _path(tmp_path, "sample").write_text(_MINIMAL, encoding="utf-8")
    other = _MINIMAL.replace('id = "sample"', 'id = "two"')
    _path(tmp_path, "two").write_text(other, encoding="utf-8")
    found = discover_pipeline_definitions(tmp_path)
    assert {d.id for d in found} == {"sample", "two"}


SHIPPED_PIPELINE_IDS = {
    "competition_intake",
    "competition_prep",
    "deep_research",
    "weekly_close",
}  # Appendix A's own four real pipelines (docs/05_AGENTS.md:435, ADR-042 D4).


def test_the_shipped_real_pipelines_load_cleanly():
    found = discover_pipeline_definitions(SHIPPED_PIPELINES_DIR)
    assert {d.id for d in found} == SHIPPED_PIPELINE_IDS
    by_id = {d.id: d for d in found}

    assert [s.agent_id for s in by_id["competition_intake"].steps] == [
        "competition_scout", "competition_strategist", "notifier",
    ]
    assert by_id["competition_intake"].steps[1].mode == "evaluate"

    assert [s.agent_id for s in by_id["competition_prep"].steps] == [
        "competition_strategist", "critic", "competition_strategist",
    ]
    assert by_id["competition_prep"].steps[0].mode == "ideas"
    assert by_id["competition_prep"].steps[2].mode == "revise"

    assert [s.agent_id for s in by_id["deep_research"].steps] == [
        "researcher", "critic", "researcher",
    ]
    assert by_id["deep_research"].steps[2].mode == "revise"

    assert [s.agent_id for s in by_id["weekly_close"].steps] == [
        "planner", "memory_steward", "notifier",
    ]
    assert by_id["weekly_close"].steps[0].mode == "review"
    assert by_id["weekly_close"].steps[1].mode == "weekly"
