"""Unified ToolSpec-based tool system."""

import importlib
from typing import Any

from agent_factory.tooling.compiler import ToolCompiler
from agent_factory.tooling.entrypoint import ToolEntrypointLoader
from agent_factory.tooling.gateway import ToolExecutionGateway
from agent_factory.tooling.mcp_runtime import MCPRuntimeClient, MCPRuntimeError, MCPRuntimeManager
from agent_factory.tooling.providers import (
    BuiltinToolProvider,
    MCPToolProvider,
    PackageToolProvider,
    SkillMetadata,
    SkillProvider,
    ToolProviderContext,
    ToolProviderResult,
)
from agent_factory.tooling.registry import (
    ToolRegistry,
    get_factory_base_tool_ids,
    get_factory_model_tools,
    get_factory_protected_tool_ids,
    get_factory_tool_specs,
    get_factory_tools,
)
from agent_factory.tooling.schema_compiler import compile_json_schema
from agent_factory.tooling.spec import (
    ModelToolView,
    ToolEventPayload,
    ToolObservation,
    ToolRiskEvaluatorConfig,
    ToolRiskResult,
    ToolSpec,
)


def __getattr__(name: str) -> Any:
    if name in {
        "FACTORY_EXTENSION_ROOT_ENV",
        "FactoryExtensionLoadReport",
        "FactoryExtensionManager",
        "default_factory_extension_root",
    }:
        return getattr(importlib.import_module("agent_factory.tooling.factory_extensions"), name)
    raise AttributeError(name)


__all__ = [
    "ModelToolView",
    "BuiltinToolProvider",
    "FACTORY_EXTENSION_ROOT_ENV",
    "FactoryExtensionLoadReport",
    "FactoryExtensionManager",
    "MCPToolProvider",
    "MCPRuntimeClient",
    "MCPRuntimeError",
    "MCPRuntimeManager",
    "PackageToolProvider",
    "SkillMetadata",
    "SkillProvider",
    "ToolCompiler",
    "ToolEntrypointLoader",
    "ToolEventPayload",
    "ToolExecutionGateway",
    "ToolObservation",
    "ToolRiskEvaluatorConfig",
    "ToolRiskResult",
    "ToolProviderContext",
    "ToolProviderResult",
    "ToolRegistry",
    "ToolSpec",
    "compile_json_schema",
    "default_factory_extension_root",
    "get_factory_base_tool_ids",
    "get_factory_model_tools",
    "get_factory_protected_tool_ids",
    "get_factory_tool_specs",
    "get_factory_tools",
]
