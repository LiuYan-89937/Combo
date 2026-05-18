from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.tooling.providers.base import (
    RuntimeDependency,
    ToolProviderContext,
    ToolProviderResult,
    diagnostic,
)
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolRiskLevel, ToolSpec


SNAKE_CHARS = re.compile(r"[^a-z0-9_]+")


class MCPDiscoveredTool(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    risk_level: ToolRiskLevel | None = None
    risk_evaluator: ToolRiskEvaluatorConfig | None = None
    concurrent: bool | None = None


class MCPToolCatalogClient(Protocol):
    def list_tools(self) -> Iterable[MCPDiscoveredTool | dict[str, Any]]:
        ...


class MCPServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_id: str
    transport: str
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    required: bool = False
    tool_id_prefix: str | None = None
    risk_level_default: ToolRiskLevel = "medium"
    concurrent_default: bool = False
    timeout_seconds: float = Field(default=30.0, gt=0)


class MCPServersConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "mcp_servers.v0"
    servers: list[MCPServerConfig] = Field(default_factory=list)


class MCPToolProvider:
    provider_id = "mcp"

    def __init__(
        self,
        *,
        config: MCPServersConfig | dict[str, Any] | None = None,
        clients: Mapping[str, MCPToolCatalogClient] | None = None,
    ) -> None:
        self.config = config if isinstance(config, MCPServersConfig) else MCPServersConfig.model_validate(config or {})
        self.clients = dict(clients or {})

    def discover(self, context: ToolProviderContext) -> ToolProviderResult:
        result = ToolProviderResult()
        for server in self.config.servers:
            if not server.enabled:
                result.diagnostics.append(
                    diagnostic(self.provider_id, "info", "MCP server is disabled", server_id=server.server_id)
                )
                continue
            result.runtime_dependencies.append(
                RuntimeDependency(
                    dependency_id=f"mcp.{server.server_id}",
                    kind="mcp_server",
                    required=server.required,
                    details=server.model_dump(mode="json"),
                )
            )
            client = self.clients.get(server.server_id)
            if client is None:
                level = "error" if server.required else "warning"
                result.diagnostics.append(
                    diagnostic(
                        self.provider_id,
                        level,
                        "MCP client is not available for configured server",
                        server_id=server.server_id,
                    )
                )
                continue
            try:
                discovered = [MCPDiscoveredTool.model_validate(item) for item in client.list_tools()]
            except Exception as exc:
                level = "error" if server.required else "warning"
                result.diagnostics.append(
                    diagnostic(
                        self.provider_id,
                        level,
                        "failed to list MCP tools",
                        server_id=server.server_id,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue
            for tool in discovered:
                try:
                    result.tool_specs.append(_tool_spec_from_mcp_tool(server, tool))
                except Exception as exc:
                    result.diagnostics.append(
                        diagnostic(
                            self.provider_id,
                            "error",
                            "failed to convert MCP tool to ToolSpec",
                            server_id=server.server_id,
                            tool_name=tool.name,
                            error=f"{type(exc).__name__}: {exc}",
                        )
                    )
        return result


def _tool_spec_from_mcp_tool(server: MCPServerConfig, tool: MCPDiscoveredTool) -> ToolSpec:
    prefix = _snake(server.tool_id_prefix or server.server_id)
    tool_name = _snake(tool.name)
    return ToolSpec(
        id=f"{prefix}_{tool_name}",
        description=tool.description or f"MCP tool {tool.name} from server {server.server_id}.",
        entrypoint=f"mcp:{server.server_id}/{tool.name}",
        input_schema=tool.input_schema or {"type": "object", "additionalProperties": True},
        output_schema=tool.output_schema or {"type": "object", "additionalProperties": True},
        resources={},
        risk_level=tool.risk_level or server.risk_level_default,
        risk_evaluator=tool.risk_evaluator or ToolRiskEvaluatorConfig(llm_mode="on_uncertain"),
        concurrent=server.concurrent_default if tool.concurrent is None else tool.concurrent,
    )


def _snake(value: str) -> str:
    text = SNAKE_CHARS.sub("_", value.strip().lower()).strip("_")
    if not text:
        text = "tool"
    if text[0].isdigit():
        text = f"tool_{text}"
    return text
