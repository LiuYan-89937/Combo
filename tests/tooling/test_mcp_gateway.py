from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_factory.mcp_gateway import MCPGatewayClient
from agent_factory.runtime_kernel.extensions import AgentInstanceExtensionManager


class MCPGatewayTest(unittest.TestCase):
    def test_gateway_client_maps_protocol_payloads(self) -> None:
        client = _FakeGatewayClient(base_url="http://gateway", server_id="search")
        tools = client.list_tools()
        result = client.call_tool("query", {"q": "agent"})

        self.assertEqual([tool.name for tool in tools], ["query"])
        self.assertEqual(result, {"server": "search", "tool": "query", "arguments": {"q": "agent"}})

    def test_agent_instance_extension_manager_uses_gateway_clients(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "mcp_servers.json").write_text(
                json.dumps(
                    {
                        "version": "mcp_servers.v0",
                        "servers": [
                            {
                                "server_id": "search",
                                "transport": "stdio",
                                "command": "node",
                                "enabled": True,
                                "risk_level_default": "low",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch("agent_factory.runtime_kernel.extensions.manager.build_gateway_clients", return_value={"search": _FakeMCPClient("search")}),
                patch("agent_factory.runtime_kernel.extensions.manager.MCPRuntimeManager") as runtime_manager,
            ):
                manager = AgentInstanceExtensionManager(
                    extension_root=root,
                    mcp_gateway_url="http://host.docker.internal:8765",
                )
                registry, result, _report = manager.build_registry()
                tool = manager.create_tool_compiler().compile(registry.get("search_query"))
                output = tool.invoke({"q": "agent"})["output"]

        self.assertEqual([spec.id for spec in result.tool_specs], ["search_query"])
        self.assertEqual(result.system_tool_ids, ["search_query"])
        self.assertEqual(output["tool"], "query")
        runtime_manager.assert_not_called()


class _FakeGatewayClient(MCPGatewayClient):
    def _request_json(self, method: str, path: str, payload: dict | None = None) -> dict:
        if method == "GET" and path == "/tools?server_id=search":
            return {
                "version": "mcp_gateway.v0",
                "server_id": "search",
                "tools": [
                    {
                        "name": "query",
                        "description": "Search through host MCP.",
                        "input_schema": {
                            "type": "object",
                            "properties": {"q": {"type": "string"}},
                            "required": ["q"],
                            "additionalProperties": False,
                        },
                    }
                ],
            }
        if method == "POST" and path == "/call":
            return {
                "version": "mcp_gateway.v0",
                "server_id": payload["server_id"],
                "tool_name": payload["tool_name"],
                "result": {
                    "server": payload["server_id"],
                    "tool": payload["tool_name"],
                    "arguments": payload["arguments"],
                },
            }
        raise AssertionError(f"unexpected gateway request: {method} {path}")


class _FakeMCPClient:
    def __init__(self, server_id: str) -> None:
        self.server_id = server_id

    def list_tools(self) -> list[dict]:
        return [
            {
                "name": "query",
                "description": "Search through host MCP.",
                "input_schema": {
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                    "required": ["q"],
                    "additionalProperties": False,
                },
            }
        ]

    def call_tool(self, tool_name: str, arguments: dict) -> dict:
        return {
            "server": self.server_id,
            "tool": tool_name,
            "arguments": arguments,
        }


if __name__ == "__main__":
    unittest.main()
