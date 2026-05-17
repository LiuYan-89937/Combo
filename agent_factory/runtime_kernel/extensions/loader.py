from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_factory.runtime_kernel.extensions.schema import (
    AgentInstanceExtensionConfigBundle,
    AgentInstanceExtensionSources,
)
from agent_factory.tooling.providers import EnabledSkillsConfig, MCPServersConfig


class AgentInstanceExtensionConfigLoader:
    def __init__(self, extension_root: str | Path) -> None:
        self.extension_root = Path(extension_root).expanduser().resolve()

    def load(self) -> AgentInstanceExtensionConfigBundle:
        mcp_path = self.extension_root / "mcp_servers.json"
        skills_path = self.extension_root / "enabled_skills.json"
        mcp_config = MCPServersConfig.model_validate(_read_optional_json(mcp_path) or {})
        skills_config = EnabledSkillsConfig.model_validate(_read_optional_json(skills_path) or {})
        return AgentInstanceExtensionConfigBundle(
            sources=AgentInstanceExtensionSources(
                extension_root=self.extension_root,
                mcp_servers_path=mcp_path if mcp_path.is_file() else None,
                enabled_skills_path=skills_path if skills_path.is_file() else None,
            ),
            mcp_servers=mcp_config,
            enabled_skills=skills_config,
        )


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"extension config must be a JSON object: {path}")
    return payload
