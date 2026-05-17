from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from agent_factory.runtime_kernel.extensions.loader import AgentInstanceExtensionConfigLoader
from agent_factory.runtime_kernel.extensions.schema import AgentInstanceExtensionLoadReport
from agent_factory.tooling.compiler import ToolCompiler
from agent_factory.tooling.entrypoints import MCPToolClient
from agent_factory.tooling.gateway import ToolApprovalHandler
from agent_factory.tooling.mcp_runtime import MCPRuntimeManager
from agent_factory.tooling.providers import (
    MCPToolCatalogClient,
    MCPToolProvider,
    SkillProvider,
    ToolProviderContext,
    ToolProviderResult,
)
from agent_factory.tooling.registry import ToolRegistry
from agent_factory.tooling.spec import ToolSpec


class AgentInstanceExtensionManager:
    def __init__(
        self,
        *,
        extension_root: str | Path,
        mcp_catalog_clients: Mapping[str, MCPToolCatalogClient] | None = None,
        mcp_tool_clients: Mapping[str, MCPToolClient] | None = None,
    ) -> None:
        self.loader = AgentInstanceExtensionConfigLoader(extension_root)
        self.mcp_catalog_clients = dict(mcp_catalog_clients or {})
        self._configured_mcp_tool_clients = dict(mcp_tool_clients or {})
        self._effective_mcp_tool_clients: dict[str, MCPToolClient] = dict(mcp_tool_clients or {})

    def discover(self, context: ToolProviderContext | None = None) -> tuple[ToolProviderResult, AgentInstanceExtensionLoadReport]:
        bundle = self.loader.load()
        mcp_runtime = MCPRuntimeManager(bundle.mcp_servers)
        catalog_clients = self.mcp_catalog_clients or mcp_runtime.clients()
        self._effective_mcp_tool_clients = self._configured_mcp_tool_clients or mcp_runtime.clients()
        provider_context = context or ToolProviderContext(extension_root=bundle.sources.extension_root)
        if provider_context.extension_root is None:
            provider_context = provider_context.model_copy(
                update={"extension_root": bundle.sources.extension_root}
            )
        result = ToolProviderResult()
        result = result.merge(
            MCPToolProvider(config=bundle.mcp_servers, clients=catalog_clients).discover(provider_context)
        )
        result = result.merge(SkillProvider(config=bundle.enabled_skills).discover(provider_context))
        report = AgentInstanceExtensionLoadReport(
            extension_root=str(bundle.sources.extension_root),
            mcp_servers_path=str(bundle.sources.mcp_servers_path) if bundle.sources.mcp_servers_path else None,
            enabled_skills_path=str(bundle.sources.enabled_skills_path) if bundle.sources.enabled_skills_path else None,
            tool_ids=[tool.id for tool in result.tool_specs],
            prompt_fragment_ids=[fragment.fragment_id for fragment in result.prompt_fragments],
            runtime_dependency_ids=[dependency.dependency_id for dependency in result.runtime_dependencies],
            diagnostics=result.diagnostics,
        )
        return result, report

    def build_registry(
        self,
        *,
        base_tool_specs: Iterable[ToolSpec] | None = None,
        context: ToolProviderContext | None = None,
    ) -> tuple[ToolRegistry, ToolProviderResult, AgentInstanceExtensionLoadReport]:
        result, report = self.discover(context=context)
        registry = ToolRegistry(base_tool_specs)
        for spec in result.tool_specs:
            registry.register(spec)
        return registry, result, report

    def create_tool_compiler(
        self,
        *,
        package_root: str | Path | None = None,
        resources: Mapping[str, Any] | None = None,
        approval_handler: ToolApprovalHandler | None = None,
        max_revisions: int | None = None,
    ) -> ToolCompiler:
        bundle = self.loader.load()
        mcp_runtime = MCPRuntimeManager(bundle.mcp_servers)
        return ToolCompiler(
            package_root=package_root,
            allowed_python_roots=[bundle.sources.extension_root],
            resources=resources,
            approval_handler=approval_handler,
            max_revisions=max_revisions,
            mcp_clients=self._configured_mcp_tool_clients or self._effective_mcp_tool_clients or mcp_runtime.clients(),
        )

    def mcp_tool_clients(self) -> dict[str, MCPToolClient]:
        return dict(self._effective_mcp_tool_clients)
