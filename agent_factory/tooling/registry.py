from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path
from typing import Mapping

from langchain_core.tools import BaseTool

from agent_factory.tooling.compiler import ToolCompiler
from agent_factory.tooling.entrypoints import MCPToolClient
from agent_factory.tooling.factory_extensions import FactoryExtensionManager, default_factory_extension_root
from agent_factory.tooling.providers import MCPToolCatalogClient
from agent_factory.tooling.builtins import (
    get_builtin_protected_tool_ids,
    get_builtin_tool_ids,
    get_builtin_tool_specs,
)
from agent_factory.tooling.spec import ModelToolView, ToolSpec, model_tool_view


class ToolRegistry:
    def __init__(self, tools: Iterable[ToolSpec] | None = None) -> None:
        self._tools: dict[str, ToolSpec] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: ToolSpec) -> None:
        if tool.id in self._tools:
            raise ValueError(f"duplicate tool id: {tool.id}")
        self._tools[tool.id] = tool

    def get(self, tool_id: str) -> ToolSpec:
        try:
            return self._tools[tool_id]
        except KeyError as exc:
            raise KeyError(f"unknown tool id: {tool_id}") from exc

    def all(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def ids(self) -> list[str]:
        return list(self._tools.keys())

    def model_views(self) -> list[ModelToolView]:
        return [model_tool_view(tool) for tool in self._tools.values()]


def get_factory_tools(
    tool_ids: Iterable[str] | None = None,
    *,
    include_extensions: bool = True,
    extension_root: str | Path | None = None,
    mcp_catalog_clients: Mapping[str, MCPToolCatalogClient] | None = None,
    mcp_tool_clients: Mapping[str, MCPToolClient] | None = None,
) -> list[BaseTool]:
    selected_ids = set(tool_ids or [])
    specs, effective_mcp_clients = _collect_factory_tool_specs(
        selected_ids=selected_ids,
        include_extensions=include_extensions,
        extension_root=extension_root,
        mcp_catalog_clients=mcp_catalog_clients,
        mcp_tool_clients=mcp_tool_clients,
    )
    factory_extension_root = Path(extension_root).expanduser().resolve() if extension_root else default_factory_extension_root()
    compiler = ToolCompiler(
        allowed_python_roots=[factory_extension_root],
        mcp_clients=effective_mcp_clients,
        resources={
            "filesystem": {
                "root": str(_default_filesystem_root()),
                "allow_external": False,
            },
            "process_runtime": {
                "root": str(_default_filesystem_root()),
                "allow_external": False,
            },
        }
    )
    return compiler.compile_many(specs)


def get_factory_tool_specs(
    tool_ids: Iterable[str] | None = None,
    *,
    include_extensions: bool = True,
    extension_root: str | Path | None = None,
    mcp_catalog_clients: Mapping[str, MCPToolCatalogClient] | None = None,
) -> list[ToolSpec]:
    selected_ids = set(tool_ids or [])
    specs, _mcp_clients = _collect_factory_tool_specs(
        selected_ids=selected_ids,
        include_extensions=include_extensions,
        extension_root=extension_root,
        mcp_catalog_clients=mcp_catalog_clients,
        mcp_tool_clients=None,
    )
    return specs


def _collect_factory_tool_specs(
    *,
    selected_ids: set[str],
    include_extensions: bool,
    extension_root: str | Path | None,
    mcp_catalog_clients: Mapping[str, MCPToolCatalogClient] | None,
    mcp_tool_clients: Mapping[str, MCPToolClient] | None,
) -> tuple[list[ToolSpec], Mapping[str, MCPToolClient]]:
    specs = get_builtin_tool_specs()
    effective_mcp_clients: Mapping[str, MCPToolClient] = dict(mcp_tool_clients or {})
    if include_extensions:
        manager = FactoryExtensionManager(
            extension_root=extension_root,
            mcp_catalog_clients=mcp_catalog_clients,
            mcp_tool_clients=mcp_tool_clients,
        )
        extension_result, _report = manager.discover()
        effective_mcp_clients = manager.mcp_tool_clients()
        registry = ToolRegistry(specs)
        for spec in extension_result.tool_specs:
            if selected_ids and spec.id not in selected_ids:
                continue
            registry.register(spec)
        specs = registry.all()
    return [tool for tool in specs if not selected_ids or tool.id in selected_ids], effective_mcp_clients


def get_factory_model_tools() -> list[BaseTool]:
    return get_factory_tools()


def get_factory_base_tool_ids() -> list[str]:
    return get_builtin_tool_ids()


def get_factory_protected_tool_ids() -> list[str]:
    return get_builtin_protected_tool_ids()


def _default_filesystem_root() -> Path:
    current = Path(os.getcwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "agent_factory").is_dir():
            return candidate
    return current
