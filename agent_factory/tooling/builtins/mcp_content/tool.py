from __future__ import annotations

from typing import Any

from agent_factory.dynamic_runtime.mcp_content_runtime import MCPContentRuntime
from agent_factory.tooling.builtins.mcp_content.specs import MCP_CONTENT_RUNTIME_RESOURCE
from agent_factory.tooling.envelope import tool_envelope


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    runtime = resources.get(MCP_CONTENT_RUNTIME_RESOURCE)
    if not isinstance(runtime, MCPContentRuntime):
        raise RuntimeError("MCP content runtime is not configured")
    action = str(arguments.get("action") or "").strip()
    if action == "search":
        output = {"action": action, "items": runtime.search(_required(arguments, "query"), limit=int(arguments.get("limit", 20)))}
    elif action == "list":
        output = {"action": action, "items": runtime.list()}
    elif action == "read_resource":
        output = runtime.read_resource(_required(arguments, "server_id"), _required(arguments, "uri"))
    elif action == "get_prompt":
        raw_arguments = arguments.get("arguments") or {}
        if not isinstance(raw_arguments, dict):
            raise ValueError("prompt arguments must be an object")
        output = runtime.get_prompt(
            _required(arguments, "server_id"),
            _required(arguments, "name"),
            {str(key): str(value) for key, value in raw_arguments.items()},
        )
    else:
        raise ValueError("MCP content action must be search, list, read_resource, or get_prompt")
    return tool_envelope(output, summary=f"MCP content {action} completed")


def _required(arguments: dict[str, Any], name: str) -> str:
    value = str(arguments.get(name) or "").strip()
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value
