from __future__ import annotations

from typing import Any

from combo.dynamic_runtime.mcp_content_runtime import MCPContentRuntime
from combo.tooling.builtins.mcp_content.specs import MCP_CONTENT_RUNTIME_RESOURCE
from combo.tooling.envelope import tool_envelope


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    runtime = resources.get(MCP_CONTENT_RUNTIME_RESOURCE)
    if not isinstance(runtime, MCPContentRuntime):
        raise RuntimeError("MCP content runtime is not configured")
    action = str(arguments.get("action") or "").strip()
    if action == "read_resource":
        output = runtime.read_resource(_required(arguments, "server_name"), _required(arguments, "uri"))
    elif action == "get_prompt":
        raw_arguments = arguments.get("arguments") or {}
        if not isinstance(raw_arguments, dict):
            raise ValueError("prompt arguments must be an object")
        output = runtime.get_prompt(
            _required(arguments, "server_name"),
            _required(arguments, "name"),
            {str(key): str(value) for key, value in raw_arguments.items()},
        )
    else:
        raise ValueError("MCP content action must be read_resource or get_prompt")
    return tool_envelope(output, summary=f"MCP content {action} completed")


def _required(arguments: dict[str, Any], name: str) -> str:
    value = str(arguments.get(name) or "").strip()
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value
