from __future__ import annotations

import unittest
from unittest.mock import patch

from agent_factory.tooling.mcp_runtime import MCPRuntimeClient, MCPRuntimeManager
from agent_factory.tooling.providers import MCPServerConfig, MCPServersConfig


class MCPRuntimeTest(unittest.TestCase):
    def test_stdio_runtime_lists_and_calls_tools_through_sdk(self) -> None:
        server = MCPServerConfig(
            server_id="local",
            transport="stdio",
            command="node",
            args=["server.js"],
            approval_default=False,
        )
        FakeStdioClient.enter_count = 0
        with patch("agent_factory.tooling.mcp_runtime._load_mcp_sdk", return_value=_fake_sdk()):
            client = MCPRuntimeClient(server)
            tools = client.list_tools()
            cached_tools = client.list_tools()
            result = client.call_tool("echo", {"text": "hello"})

        self.assertEqual(FakeStdioClient.enter_count, 2)
        self.assertEqual(tools[0].name, "echo")
        self.assertEqual(cached_tools[0].name, "echo")
        self.assertEqual(tools[0].input_schema["properties"]["text"]["type"], "string")
        self.assertEqual(result, {"echo": "hello"})
        self.assertEqual(client.stderr_logs(), ["fake mcp server ready", "fake mcp server ready"])

    def test_runtime_manager_exposes_enabled_clients(self) -> None:
        manager = MCPRuntimeManager(
            MCPServersConfig(
                servers=[
                    MCPServerConfig(server_id="enabled", transport="stdio", command="node"),
                    MCPServerConfig(server_id="disabled", transport="stdio", command="node", enabled=False),
                ]
            )
        )

        self.assertEqual(list(manager.clients().keys()), ["enabled"])


def _fake_sdk() -> dict:
    return {
        "ClientSession": FakeClientSession,
        "StdioServerParameters": FakeStdioServerParameters,
        "stdio_client": lambda params, errlog=None: FakeStdioClient(params, errlog=errlog),
    }


class FakeStdioServerParameters:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


class FakeStdioClient:
    enter_count = 0

    def __init__(self, params: FakeStdioServerParameters, errlog=None) -> None:
        self.params = params
        self.errlog = errlog

    async def __aenter__(self):
        FakeStdioClient.enter_count += 1
        if self.errlog is not None:
            self.errlog.write("fake mcp server ready\n")
        return "read_stream", "write_stream"

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class FakeClientSession:
    def __init__(self, read_stream, write_stream) -> None:
        self.read_stream = read_stream
        self.write_stream = write_stream

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def initialize(self) -> dict:
        return {"ok": True}

    async def list_tools(self) -> dict:
        return {
            "tools": [
                {
                    "name": "echo",
                    "description": "Echo text.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                    },
                }
            ]
        }

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        return {"structuredContent": {"echo": arguments["text"]}}


if __name__ == "__main__":
    unittest.main()
