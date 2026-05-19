from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.paths import project_root
from agent_factory.runtime_kernel.extensions.loader import AgentInstanceExtensionConfigLoader
from agent_factory.tooling.entrypoints import MCPToolClient
from agent_factory.tooling.mcp_runtime import MCPRuntimeManager
from agent_factory.tooling.providers import (
    MCPToolCatalogClient,
    MCPToolProvider,
    SkillProvider,
    ToolProviderContext,
    ToolProviderResult,
)


FACTORY_EXTENSION_ROOT_ENV = "AGENTFACTORY_FACTORY_EXTENSION_ROOT"


class FactoryExtensionLoadReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "factory_extension_load.v0"
    extension_root: str
    mcp_servers_path: str | None = None
    enabled_skills_path: str | None = None
    tool_ids: list[str] = Field(default_factory=list)
    system_tool_ids: list[str] = Field(default_factory=list)
    prompt_fragment_ids: list[str] = Field(default_factory=list)
    runtime_dependency_ids: list[str] = Field(default_factory=list)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)


class FactoryExtensionManager:
    def __init__(
        self,
        *,
        extension_root: str | Path | None = None,
        mcp_catalog_clients: Mapping[str, MCPToolCatalogClient] | None = None,
        mcp_tool_clients: Mapping[str, MCPToolClient] | None = None,
    ) -> None:
        self.extension_root = Path(extension_root).expanduser().resolve() if extension_root else default_factory_extension_root()
        self.loader = AgentInstanceExtensionConfigLoader(self.extension_root)
        self.mcp_catalog_clients = dict(mcp_catalog_clients or {})
        self._configured_mcp_tool_clients = dict(mcp_tool_clients or {})
        self._effective_mcp_tool_clients: dict[str, MCPToolClient] = dict(mcp_tool_clients or {})

    def discover(self, context: ToolProviderContext | None = None) -> tuple[ToolProviderResult, FactoryExtensionLoadReport]:
        bundle = self.loader.load()
        mcp_runtime = MCPRuntimeManager(bundle.mcp_servers)
        catalog_clients = self.mcp_catalog_clients or mcp_runtime.clients()
        self._effective_mcp_tool_clients = self._configured_mcp_tool_clients or mcp_runtime.clients()
        provider_context = context or ToolProviderContext(extension_root=bundle.sources.extension_root)
        if provider_context.extension_root is None:
            provider_context = provider_context.model_copy(update={"extension_root": bundle.sources.extension_root})
        result = ToolProviderResult()
        result = result.merge(
            MCPToolProvider(config=bundle.mcp_servers, clients=catalog_clients).discover(provider_context)
        )
        result = result.merge(SkillProvider(config=bundle.enabled_skills).discover(provider_context))
        report = FactoryExtensionLoadReport(
            extension_root=str(bundle.sources.extension_root),
            mcp_servers_path=str(bundle.sources.mcp_servers_path) if bundle.sources.mcp_servers_path else None,
            enabled_skills_path=str(bundle.sources.enabled_skills_path) if bundle.sources.enabled_skills_path else None,
            tool_ids=[tool.id for tool in result.tool_specs],
            system_tool_ids=list(result.system_tool_ids),
            prompt_fragment_ids=[fragment.fragment_id for fragment in result.prompt_fragments],
            runtime_dependency_ids=[dependency.dependency_id for dependency in result.runtime_dependencies],
            diagnostics=[diagnostic.model_dump(mode="json") for diagnostic in result.diagnostics],
        )
        return result, report

    def mcp_tool_clients(self) -> dict[str, MCPToolClient]:
        return dict(self._effective_mcp_tool_clients)


def default_factory_extension_root() -> Path:
    configured = os.getenv(FACTORY_EXTENSION_ROOT_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    return project_root() / ".agentfactory" / "factory" / "extensions"
