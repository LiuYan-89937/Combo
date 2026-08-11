from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from threading import RLock, Thread
from types import MappingProxyType
from typing import Any, AsyncIterator, Mapping

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from agent_factory.tooling.envelope import tool_envelope


@dataclass(frozen=True, slots=True)
class MCPServerRuntimeBinding:
    transport: str
    executable: str | None
    arguments: tuple[str, ...]
    endpoint: str | None
    working_directory: Path | None
    environment: Mapping[str, str]
    headers: Mapping[str, str]
    connect_timeout_seconds: float
    request_timeout_seconds: float
    max_parallel_requests: int

    def __post_init__(self) -> None:
        if self.transport not in {"stdio", "streamable_http", "sse"}:
            raise ValueError("unsupported MCP transport")
        if self.transport == "stdio" and (not self.executable or self.endpoint is not None):
            raise ValueError("stdio MCP binding requires executable and forbids endpoint")
        if self.transport != "stdio" and (not self.endpoint or self.executable is not None):
            raise ValueError("HTTP MCP binding requires endpoint and forbids executable")
        if self.connect_timeout_seconds <= 0 or self.request_timeout_seconds <= 0:
            raise ValueError("MCP timeouts must be positive")
        if self.max_parallel_requests < 1:
            raise ValueError("MCP maximum parallel requests must be positive")
        object.__setattr__(self, "environment", MappingProxyType(dict(self.environment)))
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))


class MCPRuntimePool:
    """Own revision-bound MCP connection settings and bounded request lanes."""

    def __init__(self) -> None:
        self._bindings: dict[str, MCPServerRuntimeBinding] = {}
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._lock = RLock()
        self._loop = asyncio.new_event_loop()
        self._thread = Thread(target=self._run_loop, name="mcp-runtime-pool", daemon=True)
        self._closed = False
        self._thread.start()

    def register(self, server_content_digest: str, binding: MCPServerRuntimeBinding) -> bool:
        with self._lock:
            if self._closed:
                raise RuntimeError("MCP runtime pool is closed")
            existing = self._bindings.get(server_content_digest)
            if existing is not None and existing != binding:
                raise RuntimeError("MCP server revision was registered with conflicting runtime settings")
            if existing is not None:
                return False
            self._bindings[server_content_digest] = binding
            return True

    def unregister(self, server_content_digest: str) -> None:
        with self._lock:
            self._bindings.pop(server_content_digest, None)
            self._semaphores.pop(server_content_digest, None)

    def discover_tools(self, server_content_digest: str) -> tuple[Any, ...]:
        binding = self._binding(server_content_digest)
        result = self._submit(
            self._list_tools(server_content_digest),
            timeout=binding.connect_timeout_seconds + binding.request_timeout_seconds,
        )
        return tuple(result)

    def call_tool(
        self,
        server_content_digest: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        binding = self._binding(server_content_digest)
        result = self._submit(
            self._call_tool(server_content_digest, tool_name, arguments),
            timeout=binding.connect_timeout_seconds + binding.request_timeout_seconds,
        )
        payload = result.model_dump(mode="json", exclude_none=True)
        return tool_envelope(
            {"server_revision": server_content_digest, "tool": tool_name, "result": payload},
            summary=f"MCP tool {tool_name} completed",
        )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join()
        self._loop.close()

    def _submit(self, operation: Any, *, timeout: float) -> Any:
        with self._lock:
            if self._closed:
                operation.close()
                raise RuntimeError("MCP runtime pool is closed")
        future = asyncio.run_coroutine_threadsafe(operation, self._loop)
        try:
            return future.result(timeout=timeout)
        except BaseException:
            future.cancel()
            raise

    async def _list_tools(self, digest: str) -> Any:
        binding = self._binding(digest)
        async with self._request_lane(digest, binding):
            async with self._session(binding) as session:
                page = await session.list_tools()
                tools = list(page.tools)
                cursor = page.nextCursor
                while cursor is not None:
                    page = await session.list_tools(cursor=cursor)
                    tools.extend(page.tools)
                    cursor = page.nextCursor
                return tuple(tools)

    async def _call_tool(self, digest: str, name: str, arguments: dict[str, Any]) -> Any:
        binding = self._binding(digest)
        async with self._request_lane(digest, binding):
            async with self._session(binding) as session:
                return await session.call_tool(
                    name,
                    arguments,
                    read_timeout_seconds=timedelta(seconds=binding.request_timeout_seconds),
                )

    @asynccontextmanager
    async def _request_lane(
        self,
        digest: str,
        binding: MCPServerRuntimeBinding,
    ) -> AsyncIterator[None]:
        semaphore = self._semaphores.get(digest)
        if semaphore is None:
            semaphore = asyncio.Semaphore(binding.max_parallel_requests)
            self._semaphores[digest] = semaphore
        async with semaphore:
            yield

    @asynccontextmanager
    async def _session(self, binding: MCPServerRuntimeBinding) -> AsyncIterator[ClientSession]:
        if binding.transport == "stdio":
            parameters = StdioServerParameters(
                command=str(binding.executable),
                args=list(binding.arguments),
                env=dict(binding.environment) or None,
                cwd=binding.working_directory,
            )
            async with stdio_client(parameters) as (read_stream, write_stream):
                async with ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=timedelta(seconds=binding.request_timeout_seconds),
                ) as session:
                    await asyncio.wait_for(session.initialize(), binding.connect_timeout_seconds)
                    yield session
            return
        if binding.transport == "streamable_http":
            async with httpx.AsyncClient(headers=dict(binding.headers)) as client:
                async with streamable_http_client(
                    str(binding.endpoint),
                    http_client=client,
                ) as (read_stream, write_stream, _):
                    async with ClientSession(read_stream, write_stream) as session:
                        await asyncio.wait_for(session.initialize(), binding.connect_timeout_seconds)
                        yield session
            return
        async with sse_client(
            str(binding.endpoint),
            headers=dict(binding.headers),
            timeout=binding.connect_timeout_seconds,
            sse_read_timeout=binding.request_timeout_seconds,
        ) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await asyncio.wait_for(session.initialize(), binding.connect_timeout_seconds)
                yield session

    def _binding(self, digest: str) -> MCPServerRuntimeBinding:
        with self._lock:
            binding = self._bindings.get(digest)
        if binding is None:
            raise RuntimeError(f"MCP server revision is not registered: {digest}")
        return binding

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()
