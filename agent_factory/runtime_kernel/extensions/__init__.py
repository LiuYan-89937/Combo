from __future__ import annotations

from typing import Any


__all__ = [
    "AgentInstanceExtensionConfigBundle",
    "AgentInstanceExtensionConfigLoader",
    "AgentInstanceExtensionLoadReport",
    "AgentInstanceExtensionManager",
    "AgentInstanceExtensionSources",
]


def __getattr__(name: str) -> Any:
    if name == "AgentInstanceExtensionConfigLoader":
        from agent_factory.runtime_kernel.extensions.loader import AgentInstanceExtensionConfigLoader

        return AgentInstanceExtensionConfigLoader
    if name == "AgentInstanceExtensionManager":
        from agent_factory.runtime_kernel.extensions.manager import AgentInstanceExtensionManager

        return AgentInstanceExtensionManager
    if name in {
        "AgentInstanceExtensionConfigBundle",
        "AgentInstanceExtensionLoadReport",
        "AgentInstanceExtensionSources",
    }:
        from agent_factory.runtime_kernel.extensions import schema

        return getattr(schema, name)
    raise AttributeError(name)
