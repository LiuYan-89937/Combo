from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.tooling.providers.base import (
    RuntimeDependency,
    ToolProviderContext,
    ToolProviderResult,
    diagnostic,
)
from agent_factory.tooling.skills import (
    SKILL_TOOL_ID,
    SkillRegistry,
    build_skill_tool_spec,
    parse_skill_directory,
)


class EnabledSkillConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str
    enabled: bool = True
    source: str = "local"
    path: str
    required: bool = False


class EnabledSkillsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "enabled_skills.v0"
    skills: list[EnabledSkillConfig] = Field(default_factory=list)


class SkillProvider:
    provider_id = "skill"

    def __init__(self, *, config: EnabledSkillsConfig | dict[str, Any] | None = None) -> None:
        self.config = config if isinstance(config, EnabledSkillsConfig) else EnabledSkillsConfig.model_validate(config or {})

    def discover(self, context: ToolProviderContext) -> ToolProviderResult:
        result = ToolProviderResult()
        registry = SkillRegistry()
        for item in self.config.skills:
            if not item.enabled:
                result.diagnostics.append(diagnostic(self.provider_id, "info", "Skill is disabled", skill_id=item.skill_id))
                continue
            skill_root = _resolve_skill_root(item.path, context.extension_root)
            try:
                skill = parse_skill_directory(skill_root)
                if skill.name != item.skill_id:
                    raise ValueError(f"enabled skill_id must match SKILL.md name: {item.skill_id} != {skill.name}")
                registry.register(skill)
                result.runtime_dependencies.append(
                    RuntimeDependency(
                        dependency_id=f"skill.{skill.name}",
                        kind="skill_runtime",
                        required=item.required,
                        details={"path": str(skill_root), "source": item.source},
                    )
                )
                _append_mcp_dependency(result, item, skill_root, skill.name)
            except Exception as exc:
                level = "error" if item.required else "warning"
                result.diagnostics.append(
                    diagnostic(
                        self.provider_id,
                        level,
                        "failed to discover Skill",
                        skill_id=item.skill_id,
                        path=str(skill_root),
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
        payload = registry.to_resource_payload()
        if payload["skills"]:
            result.runtime_resources["skills"] = payload
            result.tool_specs.append(build_skill_tool_spec(registry))
            result.system_tool_ids.append(SKILL_TOOL_ID)
        return result


def _resolve_skill_root(path: str, extension_root: Path | None) -> Path:
    skill_root = Path(path).expanduser()
    if not skill_root.is_absolute() and extension_root is not None:
        skill_root = extension_root / skill_root
    return skill_root.resolve()


def _append_mcp_dependency(
    result: ToolProviderResult,
    item: EnabledSkillConfig,
    skill_root: Path,
    skill_name: str,
) -> None:
    mcp_dependencies = skill_root / "mcp_dependencies.json"
    if not mcp_dependencies.is_file():
        return
    result.runtime_dependencies.append(
        RuntimeDependency(
            dependency_id=f"skill.{skill_name}.mcp_dependencies",
            kind="mcp_server",
            required=item.required,
            details=_read_json(mcp_dependencies),
        )
    )


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON file must contain an object: {path}")
    return payload
