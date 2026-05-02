from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field

from agent_factory.core.types import JsonDumpMixin
from agent_factory.package import PackageLoader


class MCPHealthCheckResult(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    status: str
    server_id: str
    tool_count: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "passed"


class MCPToolResult(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    server_id: str
    tool_name: str
    status: str
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class MCPClient:
    """Minimal JSONL stdio client for the MVP mock MCP server."""

    def __init__(self, command: list[str], *, timeout_seconds: int = 5) -> None:
        self.command = command
        self.timeout_seconds = timeout_seconds

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert process.stdin is not None
        assert process.stdout is not None
        request = {
            "jsonrpc": "2.0",
            "id": uuid.uuid4().hex,
            "method": method,
            "params": params or {},
        }
        stdout, stderr = process.communicate(
            json.dumps(request, ensure_ascii=False) + "\n",
            timeout=self.timeout_seconds,
        )
        if process.returncode not in {0, None} and not stdout:
            raise RuntimeError(stderr.strip() or f"MCP process exited {process.returncode}")
        for line in stdout.splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            if "error" in data:
                raise RuntimeError(str(data["error"]))
            return data.get("result") or {}
        return {}


class MCPClientManager:
    def __init__(self, package_path: str | Path, *, loader: PackageLoader | None = None) -> None:
        self.package_path = Path(package_path)
        self.loader = loader or PackageLoader()
        self.package = self.loader.load_full_package(self.package_path)

    def health_check(self) -> list[MCPHealthCheckResult]:
        results: list[MCPHealthCheckResult] = []
        for server in self.package.mcp.servers:
            if not server.enabled:
                results.append(MCPHealthCheckResult(status="skipped", server_id=server.id))
                continue
            try:
                tools = self._client_for(server.id).request("tools/list")
                results.append(
                    MCPHealthCheckResult(
                        status="passed",
                        server_id=server.id,
                        tool_count=len(tools.get("tools") or []),
                    )
                )
            except Exception as error:
                results.append(
                    MCPHealthCheckResult(status="failed", server_id=server.id, error=str(error))
                )
        return results

    def call_tool(
        self,
        capability_ref: str,
        arguments: dict[str, Any],
    ) -> MCPToolResult:
        binding = next(
            (item for item in self.package.mcp.bindings if item.capability_ref == capability_ref),
            None,
        )
        if binding is None:
            return MCPToolResult(
                server_id="unknown",
                tool_name=capability_ref,
                status="failed",
                error="MCP binding not found.",
            )
        tool_name = capability_ref.split(".")[-1].split("@")[0]
        try:
            output = self._client_for(binding.source_id).request(
                "tools/call",
                {"name": tool_name, "arguments": arguments},
            )
            return MCPToolResult(
                server_id=binding.source_id,
                tool_name=tool_name,
                status="completed",
                output=output,
            )
        except Exception as error:
            return MCPToolResult(
                server_id=binding.source_id,
                tool_name=tool_name,
                status="failed",
                error=str(error),
            )

    def _client_for(self, server_id: str) -> MCPClient:
        server = next(server for server in self.package.mcp.servers if server.id == server_id)
        if server.command:
            command = [server.command, *server.args]
        else:
            command = [sys.executable, str(self.package_path / "examples" / "mcp_server.py")]
        return MCPClient(command)
