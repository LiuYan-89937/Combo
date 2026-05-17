from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.tooling.providers.base import (
    PromptFragment,
    RuntimeDependency,
    ToolProviderContext,
    ToolProviderResult,
    diagnostic,
)
from agent_factory.tooling.providers.package import normalize_python_entrypoint
from agent_factory.tooling.spec import ToolSpec


SNAKE_CHARS = re.compile(r"[^a-z0-9_]+")


class EnabledSkillConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str
    enabled: bool = True
    source: str = "local"
    path: str
    required: bool = False
    expose_tools: bool = True
    expose_prompt_fragments: bool = True


class EnabledSkillsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "enabled_skills.v0"
    skills: list[EnabledSkillConfig] = Field(default_factory=list)


class SkillManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "skill.v0"
    skill_id: str
    description: str = ""
    tool_id_prefix: str | None = None
    default_enabled_tools: list[str] = Field(default_factory=list)
    prompt_fragments: list[str] = Field(default_factory=list)


class SkillProvider:
    provider_id = "skill"

    def __init__(self, *, config: EnabledSkillsConfig | dict[str, Any] | None = None) -> None:
        self.config = config if isinstance(config, EnabledSkillsConfig) else EnabledSkillsConfig.model_validate(config or {})

    def discover(self, context: ToolProviderContext) -> ToolProviderResult:
        result = ToolProviderResult()
        for item in self.config.skills:
            if not item.enabled:
                result.diagnostics.append(diagnostic(self.provider_id, "info", "Skill is disabled", skill_id=item.skill_id))
                continue
            skill_root = Path(item.path).expanduser()
            if not skill_root.is_absolute() and context.extension_root is not None:
                skill_root = context.extension_root / skill_root
            skill_root = skill_root.resolve()
            try:
                skill_result = self._discover_skill(item, skill_root)
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
                continue
            result = result.merge(skill_result)
        return result

    def _discover_skill(self, item: EnabledSkillConfig, skill_root: Path) -> ToolProviderResult:
        manifest_path = skill_root / "skill.json"
        manifest = SkillManifest.model_validate(_read_json(manifest_path))
        result = ToolProviderResult()
        result.runtime_dependencies.append(
            RuntimeDependency(
                dependency_id=f"skill.{manifest.skill_id}",
                kind="skill_runtime",
                required=item.required,
                details={"path": str(skill_root), "source": item.source},
            )
        )
        if item.expose_prompt_fragments:
            for fragment in manifest.prompt_fragments:
                fragment_path = (skill_root / fragment).resolve()
                _assert_inside(skill_root, fragment_path)
                result.prompt_fragments.append(
                    PromptFragment(
                        fragment_id=f"{manifest.skill_id}:{fragment}",
                        content=fragment_path.read_text(encoding="utf-8"),
                        source=str(fragment_path),
                    )
                )
        if item.expose_tools:
            result.tool_specs.extend(_load_skill_tools(skill_root, manifest))
        mcp_dependencies = skill_root / "mcp_dependencies.json"
        if mcp_dependencies.is_file():
            result.runtime_dependencies.append(
                RuntimeDependency(
                    dependency_id=f"skill.{manifest.skill_id}.mcp_dependencies",
                    kind="mcp_server",
                    required=item.required,
                    details=_read_json(mcp_dependencies),
                )
            )
        return result


def _load_skill_tools(skill_root: Path, manifest: SkillManifest) -> list[ToolSpec]:
    tools_root = skill_root / "tools"
    if not tools_root.exists():
        return []
    enabled = set(manifest.default_enabled_tools)
    specs: list[ToolSpec] = []
    for path in sorted(tools_root.glob("*.json")):
        payload = _read_json(path)
        raw_tool_id = str(payload.get("id") or "")
        normalized_tool_id = _skill_tool_id(raw_tool_id, manifest)
        if enabled and raw_tool_id not in enabled and normalized_tool_id not in enabled:
            continue
        payload["id"] = normalized_tool_id
        payload["entrypoint"] = _normalize_skill_entrypoint(str(payload.get("entrypoint") or ""), skill_root)
        specs.append(ToolSpec.model_validate(payload))
    return specs


def _skill_tool_id(tool_id: str, manifest: SkillManifest) -> str:
    tool_id = _snake(tool_id)
    if not manifest.tool_id_prefix:
        return tool_id
    prefix = _snake(manifest.tool_id_prefix)
    if tool_id == prefix or tool_id.startswith(f"{prefix}_"):
        return tool_id
    return f"{prefix}_{tool_id}"


def _normalize_skill_entrypoint(entrypoint: str, skill_root: Path) -> str:
    normalized = normalize_python_entrypoint(entrypoint)
    if not normalized.startswith("python:"):
        return normalized
    target = normalized.removeprefix("python:")
    path_text, function_name = target.rsplit(":", 1)
    path = Path(path_text).expanduser()
    if path.is_absolute():
        absolute_path = path.resolve()
    else:
        absolute_path = (skill_root / path).resolve()
    _assert_inside(skill_root, absolute_path)
    return f"python:{absolute_path}:{function_name}"


def _snake(value: str) -> str:
    text = SNAKE_CHARS.sub("_", value.strip().lower()).strip("_")
    if not text:
        text = "tool"
    if text[0].isdigit():
        text = f"tool_{text}"
    return text


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_inside(root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Skill path escapes skill root: {path}") from exc
