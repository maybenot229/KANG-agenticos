"""Agent definition loader — `agents/definitions/{id}/{id}.toml`, parsed
and structurally validated (AG-004, ADR-040).

Layer: adapters/config (the config adapter; TOML parsing and filesystem
discovery are I/O at the boundary — mirrors `permissions_loader.py`'s
own shape).
Constitutional home: 05_AGENTS AG-004, 17_PROJECT_STRUCTURE (`agents/
definitions/{name}/` — TOML + prompts, `docs/17_PROJECT_STRUCTURE.md:
103`), ADR-040 D1-D3.

Structural validation ONLY — required fields, types, the `kind` enum,
`prompt_file`/`escalation` shape rules, folder/id consistency, no
duplicate ids. The pairing lint against each definition's own `scopes`
needs `kernel/permissions/pairing.py`, which adapters may not import
(17 §4.3) — that half runs in `kernel/orchestrator/registry.py`,
composed with this loader at the composition root, exactly the split
`permissions_loader.py`/`kernel/permissions/engine.py::build_checked_
engine` already established for grants.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from kang.domain.ports.agent_definition import (
    AGENT_KINDS,
    AgentDefinition,
    AgentDefinitionInvalid,
    EscalationCapability,
)
from kang.domain.ports.model_provider import TASK_CLASSES

__all__ = ["discover_agent_definitions", "parse_agent_definition"]

_REQUIRED_STRING_FIELDS = ("id", "kind", "mandate", "degradation")


def _require_str(data: dict, field: str, context: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise AgentDefinitionInvalid(f"{context}: {field!r} must be a non-empty string")
    return value


def _string_tuple(data: dict, field: str, context: str) -> tuple[str, ...]:
    value = data.get(field)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise AgentDefinitionInvalid(f"{context}: {field!r} must be a list of strings")
    if any(not v.strip() for v in value):
        raise AgentDefinitionInvalid(f"{context}: {field!r} entries must be non-empty")
    if len(set(value)) != len(value):
        raise AgentDefinitionInvalid(f"{context}: {field!r} has a duplicate entry")
    return tuple(value)


def _parse_escalation(data: Any, context: str) -> EscalationCapability | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise AgentDefinitionInvalid(f"{context}: [escalation] must be a table")
    task_class = _require_str(data, "task_class", f"{context} escalation")
    if task_class not in TASK_CLASSES:
        raise AgentDefinitionInvalid(
            f"{context}: escalation.task_class {task_class!r} is not one "
            f"of {TASK_CLASSES}"
        )
    prompt_file = _require_str(data, "prompt_file", f"{context} escalation")
    return EscalationCapability(task_class=task_class, prompt_file=prompt_file)


def _parse_bounds(data: dict, context: str) -> tuple[int, int]:
    timeout_s = data.get("timeout_s")
    if not isinstance(timeout_s, int) or isinstance(timeout_s, bool) or timeout_s <= 0:
        raise AgentDefinitionInvalid(
            f"{context}: 'timeout_s' must be a positive integer"
        )
    retry = data.get("retry")
    if not isinstance(retry, int) or isinstance(retry, bool) or retry < 0:
        raise AgentDefinitionInvalid(
            f"{context}: 'retry' must be a non-negative integer"
        )
    return timeout_s, retry


def _check_prompt_and_escalation_shape(
    *,
    kind: str,
    prompt_file: str | None,
    escalation: EscalationCapability | None,
    folder: Path,
    context: str,
) -> None:
    """AG-002/§1.2: a cognitive agent needs a prompt and cannot declare
    an escalation (it already runs cognitively); a mechanical agent
    cannot set a prompt directly but MAY declare an escalation (§1.2's
    `M→C` shape) — 11 §4: split out of `parse_agent_definition` purely
    to keep that function under the size lint's line limit."""
    if kind == "cognitive":
        if not prompt_file:
            raise AgentDefinitionInvalid(
                f"{context}: cognitive agents require 'prompt_file'"
            )
        if escalation is not None:
            raise AgentDefinitionInvalid(
                f"{context}: cognitive agents cannot declare [escalation]"
            )
        if not (folder / prompt_file).is_file():
            raise AgentDefinitionInvalid(
                f"{context}: prompt_file {prompt_file!r} does not exist under {folder}"
            )
    else:  # mechanical
        if prompt_file is not None:
            raise AgentDefinitionInvalid(
                f"{context}: mechanical agents cannot set 'prompt_file'"
            )
        if escalation is not None and not (folder / escalation.prompt_file).is_file():
            raise AgentDefinitionInvalid(
                f"{context}: escalation.prompt_file {escalation.prompt_file!r} "
                f"does not exist under {folder}"
            )


def parse_agent_definition(toml_text: str, *, folder: Path) -> AgentDefinition:
    """Parse and structurally validate one `{id}.toml`. `folder` is the
    definition's own directory — used to resolve and check `prompt_file`/
    `escalation.prompt_file` actually exist, and to verify the folder
    name matches the declared `id` (ADR-040 D3: a mismatch refuses the
    load — a security-perimeter inconsistency, not a warning)."""
    context = f"agent definition in {folder}"
    try:
        data = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError as exc:
        raise AgentDefinitionInvalid(f"{context}: not valid TOML: {exc}") from exc

    for field in _REQUIRED_STRING_FIELDS:
        _require_str(data, field, context)

    agent_id = data["id"]
    if agent_id != folder.name:
        raise AgentDefinitionInvalid(
            f"{context}: id {agent_id!r} does not match its folder name {folder.name!r}"
        )
    context = f"agent {agent_id!r}"

    kind = data["kind"]
    if kind not in AGENT_KINDS:
        raise AgentDefinitionInvalid(f"{context}: kind {kind!r} not in {AGENT_KINDS}")

    triggers = _string_tuple(data, "triggers", context)
    # AG-005: the key MUST be present (no default toolset) — an empty
    # list IS a valid value (critic's own catalog row has no allowed
    # tools at all beyond notify); _string_tuple already permits that
    # while still requiring the key itself and rejecting empty-string/
    # duplicate entries within it.
    tools = _string_tuple(data, "tools", context)
    scopes = _string_tuple(data, "scopes", context) if "scopes" in data else ()
    timeout_s, retry = _parse_bounds(data, context)

    recipe = data.get("recipe")
    if recipe is not None and not isinstance(recipe, str):
        raise AgentDefinitionInvalid(f"{context}: 'recipe' must be a string if present")
    pipelines = _string_tuple(data, "pipelines", context) if "pipelines" in data else ()

    prompt_file = data.get("prompt_file")
    if prompt_file is not None and not isinstance(prompt_file, str):
        raise AgentDefinitionInvalid(
            f"{context}: 'prompt_file' must be a string if present"
        )
    escalation = _parse_escalation(data.get("escalation"), context)
    _check_prompt_and_escalation_shape(
        kind=kind,
        prompt_file=prompt_file,
        escalation=escalation,
        folder=folder,
        context=context,
    )

    return AgentDefinition(
        id=agent_id,
        kind=kind,
        mandate=data["mandate"],
        triggers=triggers,
        tools=tools,
        scopes=scopes,
        timeout_s=timeout_s,
        retry=retry,
        degradation=data["degradation"],
        recipe=recipe,
        pipelines=pipelines,
        prompt_file=prompt_file,
        escalation=escalation,
    )


def discover_agent_definitions(definitions_dir: Path) -> list[AgentDefinition]:
    """Load every `{id}/{id}.toml` under `definitions_dir`, structurally
    validated. Raises `AgentDefinitionInvalid` on the first bad
    definition — fails closed (ADR-040 D3), the entire load refused
    rather than a partial registry. No separate duplicate-id check:
    `parse_agent_definition`'s own folder/id match rule already makes a
    duplicate id structurally impossible while every definition lives
    directly under one flat `definitions/` directory — two folders in
    the same parent cannot share a name, and a folder's name must equal
    its own declared id. Revisit if `>20` agents ever earns the nested
    `definitions/{domain}/{name}/` grouping 17_PROJECT_STRUCTURE already
    names as a future option; that scheme would need its own id-
    uniqueness check, this one does not need one yet."""
    definitions: list[AgentDefinition] = []
    for folder in sorted(p for p in definitions_dir.iterdir() if p.is_dir()):
        manifest_path = folder / f"{folder.name}.toml"
        if not manifest_path.is_file():
            raise AgentDefinitionInvalid(
                f"agent folder {folder} has no {folder.name}.toml"
            )
        definitions.append(
            parse_agent_definition(
                manifest_path.read_text(encoding="utf-8"), folder=folder
            )
        )
    return definitions
