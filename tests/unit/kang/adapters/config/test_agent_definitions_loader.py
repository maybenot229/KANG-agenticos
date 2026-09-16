"""Agent definition loader (AG-004, ADR-040): structural parsing and
validation only — the pairing lint lives in kernel/orchestrator/
registry.py's own test file, not here (adapters may not import kernel).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kang.adapters.config.agent_definitions_loader import (
    discover_agent_definitions,
    parse_agent_definition,
)
from kang.domain.ports.agent_definition import AgentDefinitionInvalid

REPO_ROOT = Path(__file__).resolve().parents[5]
SHIPPED_DEFINITIONS_DIR = REPO_ROOT / "src" / "kang" / "agents" / "definitions"

_MECHANICAL_MINIMAL = """
id = "sweep"
kind = "mechanical"
mandate = "Sweep things."
triggers = ["sched:hourly"]
tools = ["deadlines.read"]
timeout_s = 60
retry = 1
degradation = "No degradation needed."
"""

_COGNITIVE_MINIMAL = """
id = "scribe"
kind = "cognitive"
mandate = "Write things."
triggers = ["kang"]
tools = []
timeout_s = 60
retry = 0
degradation = "Unavailable."
prompt_file = "prompts/system.md"
"""


def _folder(tmp_path: Path, name: str) -> Path:
    folder = tmp_path / name
    folder.mkdir()
    return folder


def test_parses_a_minimal_mechanical_definition(tmp_path):
    folder = _folder(tmp_path, "sweep")
    definition = parse_agent_definition(_MECHANICAL_MINIMAL, folder=folder)
    assert definition.id == "sweep"
    assert definition.kind == "mechanical"
    assert definition.tools == ("deadlines.read",)
    assert definition.scopes == ()
    assert definition.prompt_file is None
    assert definition.escalation is None


def test_parses_a_minimal_cognitive_definition_with_its_prompt_file(tmp_path):
    folder = _folder(tmp_path, "scribe")
    (folder / "prompts").mkdir()
    (folder / "prompts" / "system.md").write_text("be a scribe", encoding="utf-8")
    definition = parse_agent_definition(_COGNITIVE_MINIMAL, folder=folder)
    assert definition.kind == "cognitive"
    assert definition.prompt_file == "prompts/system.md"
    assert definition.tools == ()  # AG-005: empty tools IS valid


def test_malformed_toml_raises(tmp_path):
    with pytest.raises(AgentDefinitionInvalid, match="valid TOML"):
        parse_agent_definition("[kind\nbroken", folder=_folder(tmp_path, "x"))


@pytest.mark.parametrize("field", ["id", "kind", "mandate", "degradation"])
def test_missing_a_required_string_field_raises(tmp_path, field):
    lines = [
        line for line in _MECHANICAL_MINIMAL.strip().splitlines()
        if not line.startswith(f"{field} =")
    ]
    with pytest.raises(AgentDefinitionInvalid, match=field):
        parse_agent_definition("\n".join(lines), folder=_folder(tmp_path, "sweep"))


def test_kind_outside_the_enum_raises(tmp_path):
    text = _MECHANICAL_MINIMAL.replace('kind = "mechanical"', 'kind = "mystical"')
    with pytest.raises(AgentDefinitionInvalid, match="kind"):
        parse_agent_definition(text, folder=_folder(tmp_path, "sweep"))


def test_folder_id_mismatch_raises(tmp_path):
    folder = _folder(tmp_path, "not-sweep")
    with pytest.raises(AgentDefinitionInvalid, match="does not match"):
        parse_agent_definition(_MECHANICAL_MINIMAL, folder=folder)


@pytest.mark.parametrize("bad_value", ["0", "-5", '"soon"', "true"])
def test_non_positive_or_non_integer_timeout_raises(tmp_path, bad_value):
    text = _MECHANICAL_MINIMAL.replace("timeout_s = 60", f"timeout_s = {bad_value}")
    with pytest.raises(AgentDefinitionInvalid, match="timeout_s"):
        parse_agent_definition(text, folder=_folder(tmp_path, "sweep"))


def test_negative_retry_raises(tmp_path):
    text = _MECHANICAL_MINIMAL.replace("retry = 1", "retry = -1")
    with pytest.raises(AgentDefinitionInvalid, match="retry"):
        parse_agent_definition(text, folder=_folder(tmp_path, "sweep"))


def test_tools_key_missing_entirely_raises(tmp_path):
    # AG-005: "no default toolset" — the key itself must be declared,
    # even if empty.
    text = _MECHANICAL_MINIMAL.replace('tools = ["deadlines.read"]', "")
    with pytest.raises(AgentDefinitionInvalid, match="tools"):
        parse_agent_definition(text, folder=_folder(tmp_path, "sweep"))


def test_tools_with_a_duplicate_entry_raises(tmp_path):
    text = _MECHANICAL_MINIMAL.replace(
        'tools = ["deadlines.read"]', 'tools = ["deadlines.read", "deadlines.read"]'
    )
    with pytest.raises(AgentDefinitionInvalid, match="duplicate"):
        parse_agent_definition(text, folder=_folder(tmp_path, "sweep"))


def test_tools_with_an_empty_string_entry_raises(tmp_path):
    text = _MECHANICAL_MINIMAL.replace(
        'tools = ["deadlines.read"]', 'tools = ["deadlines.read", ""]'
    )
    with pytest.raises(AgentDefinitionInvalid, match="non-empty"):
        parse_agent_definition(text, folder=_folder(tmp_path, "sweep"))


def test_cognitive_without_prompt_file_raises(tmp_path):
    text = _COGNITIVE_MINIMAL.replace('prompt_file = "prompts/system.md"', "")
    with pytest.raises(AgentDefinitionInvalid, match="require 'prompt_file'"):
        parse_agent_definition(text, folder=_folder(tmp_path, "scribe"))


def test_cognitive_prompt_file_that_does_not_exist_raises(tmp_path):
    folder = _folder(tmp_path, "scribe")  # no prompts/system.md written
    with pytest.raises(AgentDefinitionInvalid, match="does not exist"):
        parse_agent_definition(_COGNITIVE_MINIMAL, folder=folder)


def test_mechanical_with_prompt_file_raises(tmp_path):
    text = _MECHANICAL_MINIMAL + '\nprompt_file = "prompts/system.md"\n'
    with pytest.raises(AgentDefinitionInvalid, match="cannot set 'prompt_file'"):
        parse_agent_definition(text, folder=_folder(tmp_path, "sweep"))


def test_cognitive_with_escalation_raises(tmp_path):
    folder = _folder(tmp_path, "scribe")
    (folder / "prompts").mkdir()
    (folder / "prompts" / "system.md").write_text("x", encoding="utf-8")
    text = (
        _COGNITIVE_MINIMAL
        + '\n[escalation]\ntask_class = "routine"\nprompt_file = "prompts/system.md"\n'
    )
    with pytest.raises(AgentDefinitionInvalid, match="cannot declare \\[escalation\\]"):
        parse_agent_definition(text, folder=folder)


def test_mechanical_with_a_valid_escalation(tmp_path):
    folder = _folder(tmp_path, "sweep")
    (folder / "prompts").mkdir()
    (folder / "prompts" / "escalate.md").write_text("classify this", encoding="utf-8")
    text = (
        _MECHANICAL_MINIMAL
        + '\n[escalation]\ntask_class = "classification"\n'
        'prompt_file = "prompts/escalate.md"\n'
    )
    definition = parse_agent_definition(text, folder=folder)
    assert definition.escalation is not None
    assert definition.escalation.task_class == "classification"


def test_escalation_task_class_outside_taskspecs_enum_raises(tmp_path):
    folder = _folder(tmp_path, "sweep")
    (folder / "prompts").mkdir()
    (folder / "prompts" / "escalate.md").write_text("x", encoding="utf-8")
    text = (
        _MECHANICAL_MINIMAL
        + '\n[escalation]\ntask_class = "vibes"\n'
        'prompt_file = "prompts/escalate.md"\n'
    )
    with pytest.raises(AgentDefinitionInvalid, match="task_class"):
        parse_agent_definition(text, folder=folder)


def test_escalation_prompt_file_that_does_not_exist_raises(tmp_path):
    folder = _folder(tmp_path, "sweep")
    text = (
        _MECHANICAL_MINIMAL
        + '\n[escalation]\ntask_class = "classification"\n'
        'prompt_file = "prompts/escalate.md"\n'
    )
    with pytest.raises(AgentDefinitionInvalid, match="escalation.prompt_file"):
        parse_agent_definition(text, folder=folder)


def test_discover_walks_every_folder_and_returns_all_definitions(tmp_path):
    _folder(tmp_path, "sweep").joinpath("sweep.toml").write_text(
        _MECHANICAL_MINIMAL, encoding="utf-8"
    )
    other = _MECHANICAL_MINIMAL.replace('id = "sweep"', 'id = "sweep2"')
    _folder(tmp_path, "sweep2").joinpath("sweep2.toml").write_text(
        other, encoding="utf-8"
    )
    found = discover_agent_definitions(tmp_path)
    assert {d.id for d in found} == {"sweep", "sweep2"}


def test_discover_raises_when_a_folder_has_no_matching_toml(tmp_path):
    _folder(tmp_path, "ghost")
    with pytest.raises(AgentDefinitionInvalid, match="no ghost.toml"):
        discover_agent_definitions(tmp_path)


SHIPPED_AGENT_IDS = {
    "backup_monitor", "competition_scout", "competition_strategist", "critic",
    "deadline_sweep", "faith_companion", "health_monitor", "memory_steward",
    "notifier", "planner", "researcher", "tutor", "vault_indexer",
    "vault_organizer", "web_monitor",
}  # Appendix A's own 15 — sync_agent (reserved, undefined in 16_SYNC) and
# plugin_runner (a per-plugin template, not a static catalog entry) are
# both deliberately excluded (ADR-040 D4).


def test_the_shipped_real_definitions_load_cleanly():
    found = discover_agent_definitions(SHIPPED_DEFINITIONS_DIR)
    assert {d.id for d in found} == SHIPPED_AGENT_IDS
    by_id = {d.id: d for d in found}
    assert by_id["deadline_sweep"].kind == "mechanical"
    assert by_id["critic"].tools == ("notify:digest",)  # the zero-world-tools case
    assert by_id["planner"].pipelines == ("weekly_close",)
    assert by_id["backup_monitor"].tools == (
        "backup.snapshot", "backup.verify", "backup.offsite_check",
    )  # resolved to real operations, unlike most of the catalog
    assert by_id["competition_scout"].escalation.task_class == "classification"
    assert by_id["memory_steward"].escalation.task_class == "routine"
