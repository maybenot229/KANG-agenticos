"""Pipeline definition loader — `agents/pipelines/{id}.toml`, parsed and
structurally validated (AG-002, ADR-042).

Layer: adapters/config (mirrors `agent_definitions_loader.py`'s own
shape).
Constitutional home: 05_AGENTS AG-002, 17_PROJECT_STRUCTURE (`agents/
pipelines/` — flat, one file per pipeline, `docs/17_PROJECT_STRUCTURE.md:
104`), ADR-042 D1-D3.

Structural validation ONLY — `id` non-empty and matching its own
filename stem, `steps` a non-empty list, each step's `agent_id` a
non-empty string and `mode` a string or absent. The one genuine
cross-registry check (every step's `agent_id` resolves in the real
`AgentRegistry`) needs `kernel/orchestrator/registry.py`, which adapters
may not import (17 §4.3) — that half runs in `kernel/orchestrator/
pipeline_registry.py`, composed with this loader at the composition
root, the exact split `agent_definitions_loader.py`/`kernel/
orchestrator/registry.py` already established for agent definitions
(ADR-040 D3).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from kang.domain.ports.pipeline_definition import (
    PipelineDefinition,
    PipelineDefinitionInvalid,
    PipelineStep,
)

__all__ = ["discover_pipeline_definitions", "parse_pipeline_definition"]


def _parse_step(data: object, *, index: int, context: str) -> PipelineStep:
    if not isinstance(data, dict):
        raise PipelineDefinitionInvalid(f"{context}: step {index} must be a table")
    agent_id = data.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id.strip():
        raise PipelineDefinitionInvalid(
            f"{context}: step {index}'s 'agent_id' must be a non-empty string"
        )
    mode = data.get("mode")
    if mode is not None and not isinstance(mode, str):
        raise PipelineDefinitionInvalid(
            f"{context}: step {index}'s 'mode' must be a string if present"
        )
    return PipelineStep(agent_id=agent_id, mode=mode)


def parse_pipeline_definition(toml_text: str, *, path: Path) -> PipelineDefinition:
    """Parse and structurally validate one `{id}.toml`. `path` is the
    pipeline's own file — used to verify its filename stem matches the
    declared `id` (ADR-042 D3: a mismatch refuses the load, mirroring
    ADR-040 D3's folder/id rule adapted to this flat, one-file-per-
    pipeline layout)."""
    context = f"pipeline definition at {path}"
    try:
        data = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError as exc:
        raise PipelineDefinitionInvalid(f"{context}: not valid TOML: {exc}") from exc

    pipeline_id = data.get("id")
    if not isinstance(pipeline_id, str) or not pipeline_id.strip():
        raise PipelineDefinitionInvalid(f"{context}: 'id' must be a non-empty string")
    if pipeline_id != path.stem:
        raise PipelineDefinitionInvalid(
            f"{context}: id {pipeline_id!r} does not match its filename {path.stem!r}"
        )
    context = f"pipeline {pipeline_id!r}"

    steps_data = data.get("steps")
    if not isinstance(steps_data, list) or not steps_data:
        raise PipelineDefinitionInvalid(f"{context}: 'steps' must be a non-empty list")
    steps = tuple(
        _parse_step(step, index=i, context=context)
        for i, step in enumerate(steps_data)
    )

    return PipelineDefinition(id=pipeline_id, steps=steps)


def discover_pipeline_definitions(pipelines_dir: Path) -> list[PipelineDefinition]:
    """Load every `{id}.toml` directly under `pipelines_dir` (flat
    layout, ADR-042 D1 — no per-pipeline subfolder, pipelines have no
    prompt files of their own). Raises `PipelineDefinitionInvalid` on
    the first bad pipeline — fails closed, the entire load refused
    rather than a partial registry, matching ADR-040 D3's own posture."""
    definitions: list[PipelineDefinition] = []
    for path in sorted(pipelines_dir.glob("*.toml")):
        definitions.append(
            parse_pipeline_definition(path.read_text(encoding="utf-8"), path=path)
        )
    return definitions
