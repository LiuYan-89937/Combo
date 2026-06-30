from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_factory.paths import project_root
from agent_factory.runtime_kernel.extensions.schema import (
    AgentInstanceExtensionConfigBundle,
    AgentInstanceExtensionSources,
)
from agent_factory.tooling.providers import EnabledSkillConfig, EnabledSkillsConfig, MCPServersConfig


class AgentInstanceExtensionConfigLoader:
    def __init__(
        self,
        extension_root: str | Path,
        *,
        inherited_extension_roots: list[str | Path] | tuple[str | Path, ...] | None = None,
    ) -> None:
        self.extension_root = Path(extension_root).expanduser().resolve()
        self.inherited_extension_roots = _unique_paths(
            Path(root).expanduser().resolve()
            for root in (inherited_extension_roots or [])
        )

    def load(self) -> AgentInstanceExtensionConfigBundle:
        roots = _unique_paths([*self.inherited_extension_roots, self.extension_root])
        bundles = [_load_extension_root(root) for root in roots]
        if len(bundles) == 1:
            return bundles[0]
        mcp_config = _merge_mcp_servers([bundle.mcp_servers for bundle in bundles])
        skills_config = _merge_enabled_skills(
            [
                (bundle.enabled_skills, bundle.sources.extension_root)
                for bundle in bundles
            ]
        )
        mcp_paths = [path for bundle in bundles for path in bundle.sources.mcp_servers_paths]
        skills_paths = [path for bundle in bundles for path in bundle.sources.enabled_skills_paths]
        return AgentInstanceExtensionConfigBundle(
            sources=AgentInstanceExtensionSources(
                extension_root=self.extension_root,
                extension_roots=roots,
                mcp_servers_path=mcp_paths[-1] if mcp_paths else None,
                mcp_servers_paths=mcp_paths,
                enabled_skills_path=skills_paths[-1] if skills_paths else None,
                enabled_skills_paths=skills_paths,
            ),
            mcp_servers=mcp_config,
            enabled_skills=skills_config,
        )


def default_builtin_agent_extension_root() -> Path:
    return project_root() / "SystemPackage" / "extensions"


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"extension config must be a JSON object: {path}")
    return payload


def _load_extension_root(root: Path) -> AgentInstanceExtensionConfigBundle:
    mcp_path = root / "mcp_servers.json"
    skills_path = root / "enabled_skills.json"
    mcp_config = MCPServersConfig.model_validate(_read_optional_json(mcp_path) or {})
    skills_config = EnabledSkillsConfig.model_validate(_read_optional_json(skills_path) or {})
    return AgentInstanceExtensionConfigBundle(
        sources=AgentInstanceExtensionSources(
            extension_root=root,
            extension_roots=[root],
            mcp_servers_path=mcp_path if mcp_path.is_file() else None,
            mcp_servers_paths=[mcp_path] if mcp_path.is_file() else [],
            enabled_skills_path=skills_path if skills_path.is_file() else None,
            enabled_skills_paths=[skills_path] if skills_path.is_file() else [],
        ),
        mcp_servers=mcp_config,
        enabled_skills=skills_config,
    )


def _merge_mcp_servers(configs: list[MCPServersConfig]) -> MCPServersConfig:
    by_id = {}
    for config in configs:
        for server in config.servers:
            by_id[server.server_id] = server
    return MCPServersConfig(servers=sorted(by_id.values(), key=lambda item: item.server_id))


def _merge_enabled_skills(configs: list[tuple[EnabledSkillsConfig, Path]]) -> EnabledSkillsConfig:
    by_id: dict[str, EnabledSkillConfig] = {}
    for config, root in configs:
        for skill in config.skills:
            by_id[skill.skill_id] = _normalize_skill_path(skill, root)
    return EnabledSkillsConfig(skills=sorted(by_id.values(), key=lambda item: item.skill_id))


def _normalize_skill_path(skill: EnabledSkillConfig, root: Path) -> EnabledSkillConfig:
    path = Path(skill.path).expanduser()
    if path.is_absolute():
        return skill
    return skill.model_copy(update={"path": str((root / path).resolve())})


def _unique_paths(paths: Any) -> list[Path]:
    items: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = Path(path).expanduser().resolve()
        if resolved in seen:
            continue
        items.append(resolved)
        seen.add(resolved)
    return items
