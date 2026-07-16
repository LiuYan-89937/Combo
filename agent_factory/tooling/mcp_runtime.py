from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import importlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, AsyncIterator

from agent_factory.tooling.providers.mcp import (
    MCPDiscoveredTool,
    MCPServerConfig,
    MCPServersConfig,
)


class MCPRuntimeError(RuntimeError):
    pass


class MCPRuntimeClient:
    def __init__(self, server: MCPServerConfig) -> None:
        self.server = server
        self._tool_cache: list[MCPDiscoveredTool] | None = None
        self._stderr_logs: list[str] = []

    def list_tools(self) -> list[MCPDiscoveredTool]:
        if self._tool_cache is None:
            self._tool_cache = _run_async(self._list_tools())
        return list(self._tool_cache)

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return _run_async(self._call_tool(tool_name, arguments))

    def stderr_logs(self) -> list[str]:
        return list(self._stderr_logs)

    async def _list_tools(self) -> list[MCPDiscoveredTool]:
        async with self._session() as session:
            response = await _with_timeout(
                session.list_tools(),
                timeout_seconds=self.server.timeout_seconds,
                operation=f"list tools for MCP server {self.server.server_id}",
            )
            tools = (
                response.get("tools", response)
                if isinstance(response, dict)
                else getattr(response, "tools", response)
            )
            return [_normalize_tool(tool) for tool in tools]

    async def _call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async with self._session() as session:
            result = await _with_timeout(
                session.call_tool(tool_name, arguments),
                timeout_seconds=self.server.timeout_seconds,
                operation=f"call MCP tool {self.server.server_id}/{tool_name}",
            )
            return _normalize_call_result(result)

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[Any]:
        if self.server.transport != "stdio":
            raise MCPRuntimeError(f"unsupported MCP transport: {self.server.transport}")
        if not self.server.command:
            raise MCPRuntimeError(f"MCP stdio server requires command: {self.server.server_id}")
        sdk = _load_mcp_sdk()
        env = {**os.environ, **self.server.env}
        cwd = str(Path(self.server.cwd).expanduser().resolve()) if self.server.cwd else None
        params_kwargs = {
            "command": self.server.command,
            "args": self.server.args,
            "env": env,
        }
        if cwd is not None:
            params_kwargs["cwd"] = cwd
        try:
            server_params = sdk["StdioServerParameters"](**params_kwargs)
        except TypeError:
            params_kwargs.pop("cwd", None)
            server_params = sdk["StdioServerParameters"](**params_kwargs)
        stderr_capture = _MCPStderrCapture()
        try:
            stdio_context = sdk["stdio_client"](server_params, errlog=stderr_capture)
        except TypeError:
            stdio_context = sdk["stdio_client"](server_params)
        try:
            async with stdio_context as streams:
                read_stream, write_stream = streams
                async with sdk["ClientSession"](read_stream, write_stream) as session:
                    await _with_timeout(
                        session.initialize(),
                        timeout_seconds=self.server.timeout_seconds,
                        operation=f"initialize MCP server {self.server.server_id}",
                    )
                    yield session
        finally:
            self._stderr_logs.extend(stderr_capture.lines())
            stderr_capture.close()


class MCPRuntimeManager:
    def __init__(self, config: MCPServersConfig | dict[str, Any] | None = None) -> None:
        self.config = config if isinstance(config, MCPServersConfig) else MCPServersConfig.model_validate(config or {})
        self._clients: dict[str, MCPRuntimeClient] = {
            server.server_id: _cached_client(server)
            for server in self.config.servers
            if server.enabled
        }

    def clients(self) -> dict[str, MCPRuntimeClient]:
        return dict(self._clients)


_MCP_CLIENT_CACHE: dict[str, MCPRuntimeClient] = {}


def _cached_client(server: MCPServerConfig) -> MCPRuntimeClient:
    key = json.dumps(server.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    client = _MCP_CLIENT_CACHE.get(key)
    if client is None:
        client = MCPRuntimeClient(server)
        _MCP_CLIENT_CACHE[key] = client
    return client


class _MCPStderrCapture:
    def __init__(self) -> None:
        self._file = tempfile.TemporaryFile(mode="w+t", encoding="utf-8", errors="replace")

    def write(self, value: Any) -> int:
        text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
        return self._file.write(text)

    def flush(self) -> None:
        self._file.flush()

    def fileno(self) -> int:
        return self._file.fileno()

    def lines(self) -> list[str]:
        self._file.flush()
        self._file.seek(0)
        return [line.strip() for line in self._file.read().splitlines() if line.strip()]

    def close(self) -> None:
        self._file.close()


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(coro)).result()


async def _with_timeout(coro: Any, *, timeout_seconds: float, operation: str) -> Any:
    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise MCPRuntimeError(f"{operation} timed out after {timeout_seconds:g}s") from exc


def _load_mcp_sdk() -> dict[str, Any]:
    try:
        mcp_module = importlib.import_module("mcp")
        stdio_module = importlib.import_module("mcp.client.stdio")
    except ModuleNotFoundError as exc:
        raise MCPRuntimeError("Python package 'mcp' is required to use MCP servers") from exc
    return {
        "ClientSession": mcp_module.ClientSession,
        "StdioServerParameters": mcp_module.StdioServerParameters,
        "stdio_client": stdio_module.stdio_client,
    }


def _normalize_tool(tool: Any) -> MCPDiscoveredTool:
    payload = _model_dump(tool)
    name = str(payload.get("name") or "")
    input_schema = payload.get("input_schema") or payload.get("inputSchema") or {}
    output_schema = payload.get("output_schema") or payload.get("outputSchema") or {}
    return MCPDiscoveredTool(
        name=name,
        description=str(payload.get("description") or ""),
        input_schema=input_schema if isinstance(input_schema, dict) else {},
        output_schema=output_schema if isinstance(output_schema, dict) else {},
    )


def _normalize_call_result(result: Any) -> dict[str, Any]:
    payload = _model_dump(result)
    if payload.get("isError") is True or payload.get("is_error") is True:
        raise MCPRuntimeError(_mcp_tool_error_message(payload))
    structured = payload.get("structured_content") or payload.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    content = payload.get("content")
    if content is not None:
        return {"content": content}
    return payload


def _mcp_tool_error_message(payload: dict[str, Any]) -> str:
    structured = payload.get("structured_content") or payload.get("structuredContent")
    if isinstance(structured, dict):
        for key in ("error", "message", "detail"):
            value = structured.get(key)
            if value:
                return _mcp_error_value_text(value)
    content = payload.get("content")
    if isinstance(content, list):
        messages = [
            str(item.get("text") or "").strip()
            for item in content
            if isinstance(item, dict) and str(item.get("text") or "").strip()
        ]
        if messages:
            return "\n".join(messages)
    if content:
        return _mcp_error_value_text(content)
    return "MCP tool returned isError=true without an error message"


def _mcp_error_value_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip() or "MCP tool execution failed"
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _model_dump(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json", by_alias=True)
        return dumped if isinstance(dumped, dict) else {"result": dumped}
    if hasattr(value, "dict"):
        dumped = value.dict()
        return dumped if isinstance(dumped, dict) else {"result": dumped}
    return {
        key: getattr(value, key)
        for key in dir(value)
        if not key.startswith("_") and not callable(getattr(value, key))
    }
