from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock, Thread
from types import MappingProxyType
from typing import Any, AsyncIterator, Callable, Mapping

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from combo.tooling.envelope import tool_envelope


@dataclass(frozen=True, slots=True)
class MCPServerRuntimeBinding:
    server_id: str
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
        if not self.server_id.strip():
            raise ValueError("MCP server binding requires server_id")
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


@dataclass(frozen=True, slots=True)
class MCPServerCatalog:
    protocol_version: str
    server_name: str
    server_version: str
    capabilities: tuple[str, ...]
    tools: tuple[Any, ...]
    resources: tuple[Any, ...]
    resource_templates: tuple[Any, ...]
    prompts: tuple[Any, ...]


@dataclass(slots=True)
class _PersistentConnection:
    binding: MCPServerRuntimeBinding
    ready: asyncio.Event
    stop: asyncio.Event
    session: ClientSession | None = None
    catalog: MCPServerCatalog | None = None
    error: BaseException | None = None
    task: asyncio.Task[None] | None = None
    logs: list[dict[str, Any]] | None = None


class MCPRuntimePool:
    """Own revision-bound MCP connection settings and bounded request lanes."""

    def __init__(self) -> None:
        self._bindings: dict[str, MCPServerRuntimeBinding] = {}
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._lock = RLock()
        self._loop = asyncio.new_event_loop()
        self._thread = Thread(target=self._run_loop, name="mcp-runtime-pool", daemon=True)
        self._closed = False
        self._connections: dict[str, _PersistentConnection] = {}
        self._catalog_changed_callbacks: list[Callable[[str, str], None]] = []
        self._thread.start()

    def on_catalog_changed(self, callback: Callable[[str, str], None]) -> None:
        if not callable(callback):
            raise TypeError("MCP catalog callback must be callable")
        with self._lock:
            self._catalog_changed_callbacks.append(callback)

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
        asyncio.run_coroutine_threadsafe(
            self._start_connection(server_content_digest, binding),
            self._loop,
        ).result(timeout=binding.connect_timeout_seconds)
        return True

    def unregister(self, server_content_digest: str) -> None:
        with self._lock:
            self._bindings.pop(server_content_digest, None)
            self._semaphores.pop(server_content_digest, None)
        if not self._closed:
            asyncio.run_coroutine_threadsafe(
                self._stop_connection(server_content_digest),
                self._loop,
            ).result(timeout=5)

    def retain(self, active_digests: set[str]) -> None:
        with self._lock:
            stale = tuple(set(self._bindings).difference(active_digests))
        for digest in stale:
            self.unregister(digest)

    def discover(
        self,
        server_content_digest: str,
        *,
        on_progress: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> MCPServerCatalog:
        binding = self._binding(server_content_digest)
        result = self._submit(
            self._discover(server_content_digest, on_progress=on_progress),
            timeout=binding.connect_timeout_seconds + binding.request_timeout_seconds,
        )
        return result

    def discover_tools(
        self,
        server_content_digest: str,
        *,
        on_progress: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> tuple[Any, ...]:
        return self.discover(server_content_digest, on_progress=on_progress).tools

    def catalogs(self) -> dict[str, MCPServerCatalog]:
        return self._submit(self._catalogs(), timeout=5)

    def logs(self, server_id: str) -> tuple[dict[str, Any], ...]:
        digest = self.server_digest(server_id)
        return self._submit(self._logs(digest), timeout=5)

    def server_digest(self, server_id: str) -> str:
        normalized = str(server_id or "").strip()
        with self._lock:
            matches = [digest for digest, binding in self._bindings.items() if binding.server_id == normalized]
        if len(matches) != 1:
            raise LookupError(f"active MCP server not found: {normalized}")
        return matches[0]

    def read_resource(self, server_content_digest: str, uri: str) -> dict[str, Any]:
        binding = self._binding(server_content_digest)
        result = self._submit(
            self._read_resource(server_content_digest, uri),
            timeout=binding.request_timeout_seconds,
        )
        return result.model_dump(mode="json", exclude_none=True)

    def get_prompt(
        self,
        server_content_digest: str,
        name: str,
        arguments: dict[str, str],
    ) -> dict[str, Any]:
        binding = self._binding(server_content_digest)
        result = self._submit(
            self._get_prompt(server_content_digest, name, arguments),
            timeout=binding.request_timeout_seconds,
        )
        return result.model_dump(mode="json", exclude_none=True)

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
        asyncio.run_coroutine_threadsafe(self._stop_all_connections(), self._loop).result(timeout=10)
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

    async def _discover(
        self,
        digest: str,
        *,
        on_progress: Callable[[str, dict[str, Any]], None] | None,
    ) -> MCPServerCatalog:
        binding = self._binding(digest)
        async with self._request_lane(digest, binding):
            _report_progress(on_progress, "connecting", {"transport": binding.transport})
            connection = await self._ready_connection(digest)
            catalog = await self._refresh_catalog(digest, connection)
            _report_progress(on_progress, "initialized", _catalog_identity(catalog))
            _report_progress(on_progress, "catalog_discovered", {
                "tool_count": len(catalog.tools),
                "resource_count": len(catalog.resources),
                "resource_template_count": len(catalog.resource_templates),
                "prompt_count": len(catalog.prompts),
            })
            return catalog

    async def _call_tool(self, digest: str, name: str, arguments: dict[str, Any]) -> Any:
        binding = self._binding(digest)
        async with self._request_lane(digest, binding):
            connection = await self._ready_connection(digest)
            try:
                return await connection.session.call_tool(
                    name,
                    arguments,
                    read_timeout_seconds=binding.request_timeout_seconds,
                )
            except BaseException:
                await self._restart_connection(digest, connection)
                raise

    async def _read_resource(self, digest: str, uri: str) -> Any:
        binding = self._binding(digest)
        async with self._request_lane(digest, binding):
            connection = await self._ready_connection(digest)
            try:
                return await connection.session.read_resource(uri)
            except BaseException:
                await self._restart_connection(digest, connection)
                raise

    async def _get_prompt(self, digest: str, name: str, arguments: dict[str, str]) -> Any:
        binding = self._binding(digest)
        async with self._request_lane(digest, binding):
            connection = await self._ready_connection(digest)
            try:
                return await connection.session.get_prompt(name, arguments=arguments or None)
            except BaseException:
                await self._restart_connection(digest, connection)
                raise

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
    async def _transport(self, binding: MCPServerRuntimeBinding) -> AsyncIterator[tuple[Any, Any]]:
        if binding.transport == "stdio":
            parameters = StdioServerParameters(
                command=str(binding.executable),
                args=list(binding.arguments),
                env=dict(binding.environment) or None,
                cwd=binding.working_directory,
            )
            async with stdio_client(parameters) as (read_stream, write_stream):
                yield read_stream, write_stream
            return
        if binding.transport == "streamable_http":
            async with httpx.AsyncClient(headers=dict(binding.headers)) as client:
                async with streamable_http_client(
                    str(binding.endpoint),
                    http_client=client,
                ) as (read_stream, write_stream, _):
                    yield read_stream, write_stream
            return
        async with sse_client(
            str(binding.endpoint),
            headers=dict(binding.headers),
            timeout=binding.connect_timeout_seconds,
            sse_read_timeout=binding.request_timeout_seconds,
        ) as (read_stream, write_stream):
            yield read_stream, write_stream

    async def _start_connection(self, digest: str, binding: MCPServerRuntimeBinding) -> None:
        if digest in self._connections:
            return
        connection = _PersistentConnection(
            binding=binding,
            ready=asyncio.Event(),
            stop=asyncio.Event(),
            logs=[],
        )
        self._connections[digest] = connection
        connection.task = asyncio.create_task(self._connection_worker(digest, connection))

    async def _connection_worker(self, digest: str, connection: _PersistentConnection) -> None:
        delay = 0.5
        while not connection.stop.is_set():
            try:
                async with self._transport(connection.binding) as (read_stream, write_stream):
                    async with ClientSession(
                        read_stream,
                        write_stream,
                        read_timeout_seconds=connection.binding.request_timeout_seconds,
                        logging_callback=lambda params: self._handle_log(digest, params),
                        message_handler=lambda message: self._handle_message(digest, message),
                    ) as session:
                        initialized = await asyncio.wait_for(
                            session.initialize(),
                            connection.binding.connect_timeout_seconds,
                        )
                        connection.session = session
                        connection.catalog = _empty_catalog(initialized)
                        connection.error = None
                        connection.ready.set()
                        delay = 0.5
                        await connection.stop.wait()
            except asyncio.CancelledError:
                raise
            except BaseException as exc:
                connection.error = exc
                connection.ready.set()
            finally:
                connection.session = None
            if not connection.stop.is_set():
                try:
                    await asyncio.wait_for(connection.stop.wait(), timeout=delay)
                except TimeoutError:
                    pass
                delay = min(delay * 2, 10.0)

    async def _ready_connection(self, digest: str) -> _PersistentConnection:
        connection = self._connections.get(digest)
        if connection is None:
            binding = self._binding(digest)
            await self._start_connection(digest, binding)
            connection = self._connections[digest]
        await asyncio.wait_for(connection.ready.wait(), connection.binding.connect_timeout_seconds)
        if connection.session is None:
            error = connection.error or RuntimeError("MCP connection is unavailable")
            connection.ready.clear()
            raise RuntimeError(str(error)) from error
        return connection

    async def _refresh_catalog(
        self,
        digest: str,
        connection: _PersistentConnection,
    ) -> MCPServerCatalog:
        if connection.session is None or connection.catalog is None:
            raise RuntimeError("MCP connection is unavailable")
        capabilities = set(connection.catalog.capabilities)
        tools = await _paged(connection.session.list_tools, "tools") if "tools" in capabilities else ()
        resources = await _paged(connection.session.list_resources, "resources") if "resources" in capabilities else ()
        templates = await _paged(connection.session.list_resource_templates, "resourceTemplates") if "resources" in capabilities else ()
        prompts = await _paged(connection.session.list_prompts, "prompts") if "prompts" in capabilities else ()
        catalog = MCPServerCatalog(
            protocol_version=connection.catalog.protocol_version,
            server_name=connection.catalog.server_name,
            server_version=connection.catalog.server_version,
            capabilities=connection.catalog.capabilities,
            tools=tools,
            resources=resources,
            resource_templates=templates,
            prompts=prompts,
        )
        connection.catalog = catalog
        return catalog

    async def _handle_message(self, digest: str, message: Any) -> None:
        root = getattr(message, "root", None)
        notification = type(root).__name__
        if notification == "LoggingMessageNotification":
            await self._handle_log(digest, getattr(root, "params", None))
            return
        changed = {
            "ToolListChangedNotification": "tools",
            "ResourceListChangedNotification": "resources",
            "PromptListChangedNotification": "prompts",
        }.get(notification)
        if changed is not None:
            asyncio.create_task(self._refresh_after_notification(digest, changed))

    async def _refresh_after_notification(self, digest: str, changed: str) -> None:
        await asyncio.sleep(0)
        connection = self._connections.get(digest)
        if connection is None or connection.session is None:
            return
        try:
            await self._refresh_catalog(digest, connection)
        except BaseException as exc:
            connection.error = exc
            return
        for callback in tuple(self._catalog_changed_callbacks):
            asyncio.get_running_loop().run_in_executor(None, callback, digest, changed)

    async def _catalogs(self) -> dict[str, MCPServerCatalog]:
        return {
            connection.binding.server_id: connection.catalog
            for digest, connection in self._connections.items()
            if connection.catalog is not None
        }

    async def _logs(self, digest: str) -> tuple[dict[str, Any], ...]:
        connection = self._connections.get(digest)
        return tuple(connection.logs or ()) if connection is not None else ()

    async def _handle_log(self, digest: str, params: Any) -> None:
        connection = self._connections.get(digest)
        if connection is None or connection.logs is None:
            return
        connection.logs.append({
            "level": str(getattr(params, "level", "info")),
            "logger": str(getattr(params, "logger", "") or ""),
            "data": getattr(params, "data", None),
        })
        del connection.logs[:-500]

    async def _stop_connection(self, digest: str) -> None:
        connection = self._connections.pop(digest, None)
        if connection is None:
            return
        connection.stop.set()
        if connection.task is not None:
            await connection.task

    async def _restart_connection(self, digest: str, connection: _PersistentConnection) -> None:
        current = self._connections.get(digest)
        if current is not connection:
            return
        await self._stop_connection(digest)
        await self._start_connection(digest, connection.binding)

    async def _stop_all_connections(self) -> None:
        for digest in tuple(self._connections):
            await self._stop_connection(digest)

    def _binding(self, digest: str) -> MCPServerRuntimeBinding:
        with self._lock:
            binding = self._bindings.get(digest)
        if binding is None:
            raise RuntimeError(f"MCP server revision is not registered: {digest}")
        return binding

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()


def _report_initialized(
    callback: Callable[[str, dict[str, Any]], None] | None,
    initialized: Any,
) -> None:
    server = getattr(initialized, "serverInfo", None)
    capabilities = getattr(initialized, "capabilities", None)
    _report_progress(callback, "initialized", {
        "protocol_version": str(getattr(initialized, "protocolVersion", "")),
        "server_name": str(getattr(server, "name", "")),
        "server_version": str(getattr(server, "version", "")),
        "capabilities": sorted(
            key
            for key, value in (
                capabilities.model_dump(mode="python", exclude_none=True).items()
                if capabilities is not None else ()
            )
            if value is not None
        ),
    })


def _empty_catalog(initialized: Any) -> MCPServerCatalog:
    server = getattr(initialized, "serverInfo", None)
    capabilities = getattr(initialized, "capabilities", None)
    names = tuple(sorted(
        key
        for key, value in (
            capabilities.model_dump(mode="python", exclude_none=True).items()
            if capabilities is not None else ()
        )
        if value is not None
    ))
    return MCPServerCatalog(
        protocol_version=str(getattr(initialized, "protocolVersion", "")),
        server_name=str(getattr(server, "name", "")),
        server_version=str(getattr(server, "version", "")),
        capabilities=names,
        tools=(),
        resources=(),
        resource_templates=(),
        prompts=(),
    )


def _catalog_identity(catalog: MCPServerCatalog) -> dict[str, Any]:
    return {
        "protocol_version": catalog.protocol_version,
        "server_name": catalog.server_name,
        "server_version": catalog.server_version,
        "capabilities": list(catalog.capabilities),
    }


async def _paged(request: Callable[..., Any], collection_name: str) -> tuple[Any, ...]:
    page = await request()
    values = list(getattr(page, collection_name, ()) or ())
    cursor = getattr(page, "nextCursor", None)
    while cursor is not None:
        page = await request(cursor=cursor)
        values.extend(getattr(page, collection_name, ()) or ())
        cursor = getattr(page, "nextCursor", None)
    return tuple(values)


def _report_progress(
    callback: Callable[[str, dict[str, Any]], None] | None,
    stage: str,
    detail: dict[str, Any],
) -> None:
    if callback is not None:
        callback(stage, detail)
