from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from threading import RLock
from typing import Any, Callable
from urllib.parse import quote

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from combo.dynamic_runtime.capability_definitions import (
    MCPSchemaEvidence,
    MCPSchemaRepairRecord,
    MCPToolDefinition,
    ToolRuntimePolicy,
)
from combo.dynamic_runtime.mcp_runtime import (
    MCPRuntimePool,
    MCPServerCatalog,
    MCPServerRuntimeBinding,
)
from combo.runtime_protocol import (
    CapabilityProjectionSnapshot,
    CapabilityRevisionRef,
    CapabilitySelection,
    CapabilitySnapshot,
    CapabilityToolAliasBinding,
)


MCP_GATEWAY_REGISTRY_VERSION = "mcp_gateway.v1"
MCP_GATEWAY_ADAPTER_ID = "dynamic_runtime.mcp_gateway"
MCP_GATEWAY_ADAPTER_REVISION = "1"

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_JSON_SCHEMA_TYPES = frozenset({"array", "boolean", "integer", "null", "number", "object", "string"})
_SCHEMA_VALUE_KEYWORDS = frozenset({
    "additionalItems", "additionalProperties", "contains", "contentSchema", "else", "if",
    "not", "propertyNames", "then", "unevaluatedItems", "unevaluatedProperties",
})
_SCHEMA_ARRAY_KEYWORDS = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})
_SCHEMA_MAP_KEYWORDS = frozenset({
    "$defs", "definitions", "dependentSchemas", "patternProperties", "properties",
})


@dataclass(frozen=True, slots=True)
class MCPGatewayConfig:
    registry_path: Path
    base_environment: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "registry_path", Path(self.registry_path).expanduser().resolve())


@dataclass(frozen=True, slots=True)
class MCPGatewayTool:
    capability_id: str
    server_id: str
    server_revision: int
    display_name: str
    description: str
    definition: MCPToolDefinition
    content_digest: str

    def projection(self) -> CapabilityProjectionSnapshot:
        return CapabilityProjectionSnapshot(
            capability_id=self.capability_id,
            kind="mcp_tool",
            revision=self.server_revision,
            content_digest=self.content_digest,
            adapter_id=MCP_GATEWAY_ADAPTER_ID,
            adapter_revision=MCP_GATEWAY_ADAPTER_REVISION,
            runtime_definition_schema="mcp_tool_definition.v3",
            runtime_definition=self.definition.model_dump(mode="json"),
            model_tool_ids=(self.definition.model_alias,),
        )

    def selection(self, *, reason: str) -> CapabilitySelection:
        return CapabilitySelection(
            capability_id=self.capability_id,
            kind="mcp_tool",
            status="selected",
            reason=reason,
            evidence_ids=(f"mcp-gateway:{self.definition.server_content_digest}",),
            resolved=CapabilityRevisionRef(
                capability_id=self.capability_id,
                kind="mcp_tool",
                resolved_version=self.definition.server_content_digest,
                revision=self.server_revision,
                content_digest=self.content_digest,
            ),
        )


@dataclass(frozen=True, slots=True)
class MCPGatewayServer:
    server_id: str
    revision: int
    raw_config: dict[str, Any]
    server_digest: str
    catalog: MCPServerCatalog
    tools: tuple[MCPGatewayTool, ...]


@dataclass(frozen=True, slots=True)
class MCPGatewayPreparedServer:
    server: MCPGatewayServer
    runtime_registered: bool


class MCPGateway:
    """Own external MCP configuration, live catalogs, tolerant projections, and snapshot assembly."""

    def __init__(
        self,
        *,
        config: MCPGatewayConfig,
        runtime: MCPRuntimePool,
        environment_resolver: Callable[[str], str | None] = os.environ.get,
        report_unavailable: Callable[[str, BaseException], None],
    ) -> None:
        self._config = config
        self._runtime = runtime
        self._environment_resolver = environment_resolver
        self._report_unavailable = report_unavailable
        self._lock = RLock()
        self._servers: dict[str, MCPGatewayServer] = {}

    @property
    def registry_path(self) -> Path:
        return self._config.registry_path

    def synchronize(self) -> None:
        with self._lock:
            registry = read_mcp_gateway_registry(self.registry_path)
            configured_digests: set[str] = set()
            synchronized: dict[str, MCPGatewayServer] = {}
            for raw in registry["servers"]:
                if not raw.get("enabled", True):
                    continue
                server_id = str(raw.get("server_id") or "").strip() or "<invalid>"
                try:
                    _, binding, server_digest = self._binding(raw)
                    configured_digests.add(server_digest)
                    prepared = self._prepare(raw, force_discovery=False)
                except Exception as exc:
                    self._report_unavailable(server_id, exc)
                    previous = self._servers.get(server_id)
                    if previous is not None and previous.server_digest in configured_digests:
                        synchronized[server_id] = previous
                    continue
                synchronized[server_id] = prepared.server
            self._servers = synchronized
            self._runtime.retain(configured_digests)

    def add_server(
        self,
        raw: dict[str, Any],
        *,
        expected_registry_digest: str,
        on_progress: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        with self._lock:
            current = read_mcp_gateway_registry(self.registry_path)
            self._require_registry_digest(current, expected_registry_digest)
            server_id = str(raw.get("server_id") or "").strip()
            if any(str(item.get("server_id")) == server_id for item in current["servers"]):
                raise ValueError(f"MCP server already exists: {server_id}")
            candidate = {**raw, "revision": 1}
            prepared = self._prepare(candidate, on_progress=on_progress)
            replacement = {
                **current,
                "revision": int(current["revision"]) + 1,
                "servers": [*current["servers"], candidate],
            }
            self._commit_registry_change(current, replacement, prepared)
            _progress(on_progress, "published", server_id, {})

    def replace_server(
        self,
        server_id: str,
        raw: dict[str, Any],
        *,
        expected_registry_digest: str,
        on_progress: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        with self._lock:
            current = read_mcp_gateway_registry(self.registry_path)
            self._require_registry_digest(current, expected_registry_digest)
            normalized_id = str(server_id or "").strip()
            if str(raw.get("server_id") or "").strip() != normalized_id:
                raise ValueError("MCP server identity cannot change")
            matches = [
                index for index, item in enumerate(current["servers"])
                if str(item.get("server_id")) == normalized_id
            ]
            if len(matches) != 1:
                raise LookupError(f"MCP server not found: {normalized_id}")
            existing = current["servers"][matches[0]]
            candidate = {
                **raw,
                "revision": int(existing["revision"]) + 1,
                "tools": dict(existing.get("tools") or {}),
            }
            prepared = self._prepare(candidate, on_progress=on_progress)
            servers = list(current["servers"])
            servers[matches[0]] = candidate
            replacement = {
                **current,
                "revision": int(current["revision"]) + 1,
                "servers": servers,
            }
            self._commit_registry_change(current, replacement, prepared)
            _progress(on_progress, "published", normalized_id, {})

    def delete_server(self, server_id: str, *, expected_registry_digest: str) -> None:
        with self._lock:
            current = read_mcp_gateway_registry(self.registry_path)
            self._require_registry_digest(current, expected_registry_digest)
            normalized_id = str(server_id or "").strip()
            if sum(str(item.get("server_id")) == normalized_id for item in current["servers"]) != 1:
                raise LookupError(f"MCP server not found: {normalized_id}")
            replacement = {
                **current,
                "revision": int(current["revision"]) + 1,
                "servers": [
                    item for item in current["servers"]
                    if str(item.get("server_id")) != normalized_id
                ],
            }
            write_mcp_gateway_registry(self.registry_path, replacement)
            self.synchronize()

    def replace_tool_configuration(
        self,
        capability_id: str,
        *,
        expected_content_digest: str,
        display_name: str,
        description: str,
        runtime_policy: dict[str, Any],
    ) -> None:
        with self._lock:
            tool = next(
                (item for item in self.tools() if item.capability_id == capability_id),
                None,
            )
            if tool is None:
                raise LookupError(f"connected MCP tool not found: {capability_id}")
            if tool.content_digest != str(expected_content_digest or "").strip():
                raise RuntimeError("capability_revision_conflict")
            current = read_mcp_gateway_registry(self.registry_path)
            matches = [
                index for index, item in enumerate(current["servers"])
                if str(item.get("server_id")) == tool.server_id
            ]
            if len(matches) != 1:
                raise LookupError(f"MCP server not found: {tool.server_id}")
            servers = list(current["servers"])
            server = dict(servers[matches[0]])
            overrides = dict(server.get("tools") or {})
            overrides[tool.definition.upstream_tool_name] = {
                "display_name": _required_text(display_name, "display_name"),
                "description": _required_text(description, "description"),
                "runtime_policy": ToolRuntimePolicy.model_validate(runtime_policy).model_dump(mode="json"),
            }
            server["tools"] = overrides
            server["revision"] = int(server["revision"]) + 1
            prepared = self._prepare(server)
            servers[matches[0]] = server
            replacement = {
                **current,
                "revision": int(current["revision"]) + 1,
                "servers": servers,
            }
            self._commit_registry_change(current, replacement, prepared)

    def registry_digest(self) -> str:
        return _digest(read_mcp_gateway_registry(self.registry_path))

    def registry(self) -> dict[str, Any]:
        return read_mcp_gateway_registry(self.registry_path)

    def server(self, server_id: str) -> MCPGatewayServer:
        with self._lock:
            server = self._servers.get(str(server_id or "").strip())
        if server is None:
            raise LookupError(f"connected MCP server not found: {server_id}")
        return server

    def connected_server(self, server_id: str) -> MCPGatewayServer | None:
        with self._lock:
            return self._servers.get(str(server_id or "").strip())

    def servers(self) -> tuple[MCPGatewayServer, ...]:
        with self._lock:
            return tuple(self._servers[key] for key in sorted(self._servers))

    def tools(self) -> tuple[MCPGatewayTool, ...]:
        return tuple(tool for server in self.servers() for tool in server.tools)

    def tools_for_servers(self, server_ids: tuple[str, ...]) -> tuple[MCPGatewayTool, ...]:
        requested = tuple(dict.fromkeys(str(value or "").strip() for value in server_ids))
        if any(not value for value in requested):
            raise ValueError("MCP server IDs must not be empty")
        return tuple(tool for server_id in requested for tool in self.server(server_id).tools)

    def exact_requirement_matches(
        self,
        requirements: tuple[str, ...],
    ) -> tuple[tuple[str, MCPGatewayTool], ...]:
        tools = self.tools()
        matches: list[tuple[str, MCPGatewayTool]] = []
        for requirement in requirements:
            normalized = _normalized_name(requirement)
            candidates = [
                tool for tool in tools
                if normalized in {
                    _normalized_name(tool.display_name),
                    _normalized_name(tool.definition.upstream_tool_name),
                    _normalized_name(tool.definition.model_alias),
                }
            ]
            if len(candidates) == 1:
                matches.append((requirement, candidates[0]))
        return tuple(matches)

    def augment_snapshot(
        self,
        base: CapabilitySnapshot,
        *,
        server_ids: tuple[str, ...] = (),
        required_tools: tuple[MCPGatewayTool, ...] = (),
    ) -> CapabilitySnapshot:
        unique_tools: dict[str, MCPGatewayTool] = {}
        for tool in (*self.tools_for_servers(server_ids), *required_tools):
            unique_tools.setdefault(tool.capability_id, tool)
        tools = tuple(unique_tools.values())
        if not tools:
            return base
        existing_capability_ids = {item.capability_id for item in base.selections}
        existing_aliases = set(base.tool_ids)
        additions: list[MCPGatewayTool] = []
        for tool in tools:
            if tool.capability_id in existing_capability_ids:
                continue
            if tool.definition.model_alias in existing_aliases:
                raise RuntimeError(f"MCP tool alias collides with the runtime surface: {tool.definition.model_alias}")
            existing_aliases.add(tool.definition.model_alias)
            additions.append(tool)
        projections = tuple(tool.projection() for tool in additions)
        aliases = tuple(
            CapabilityToolAliasBinding(
                model_alias=tool.definition.model_alias,
                capability_id=tool.capability_id,
                kind="mcp_tool",
                revision=tool.server_revision,
                content_digest=tool.content_digest,
            )
            for tool in additions
        )
        return CapabilitySnapshot(
            selections=(*base.selections, *(tool.selection(reason="selected by the MCP gateway") for tool in additions)),
            projections=(*base.projections, *projections),
            tool_ids=(*base.tool_ids, *(item.model_alias for item in aliases)),
            tool_aliases=(*base.tool_aliases, *aliases),
            dependency_environment=base.dependency_environment,
        )

    def _prepare(
        self,
        raw: dict[str, Any],
        *,
        force_discovery: bool = True,
        on_progress: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> MCPGatewayPreparedServer:
        server_id, binding, server_digest = self._binding(raw)
        _progress(on_progress, "validating", server_id, {})
        runtime_registered = False
        try:
            runtime_registered = self._runtime.register(server_digest, binding)
            catalog = None if force_discovery else self._runtime.cached_catalog(server_digest)
            if catalog is None:
                catalog = self._runtime.discover(
                    server_digest,
                    on_progress=lambda stage, detail: _progress(on_progress, stage, server_id, detail),
                )
            tools = self._project_tools(raw, server_digest, catalog)
        except BaseException:
            if runtime_registered:
                self._runtime.unregister(server_digest)
            raise
        _progress(on_progress, "capabilities_prepared", server_id, {
            "tool_count": len(tools),
            "resource_count": len(catalog.resources),
            "resource_template_count": len(catalog.resource_templates),
            "prompt_count": len(catalog.prompts),
            "degraded_schema_count": sum(
                tool.definition.input_schema.compatibility_status == "degraded"
                or tool.definition.output_schema.compatibility_status == "degraded"
                for tool in tools
            ),
        })
        return MCPGatewayPreparedServer(
            server=MCPGatewayServer(
                server_id=server_id,
                revision=int(raw.get("revision") or 0),
                raw_config=dict(raw),
                server_digest=server_digest,
                catalog=catalog,
                tools=tools,
            ),
            runtime_registered=runtime_registered,
        )

    def _binding(self, raw: dict[str, Any]) -> tuple[str, MCPServerRuntimeBinding, str]:
        server_id = str(raw.get("server_id") or "").strip()
        if not _IDENTIFIER.fullmatch(server_id):
            raise ValueError("MCP server_id must be a stable lowercase identifier")
        revision = int(raw.get("revision") or 0)
        if revision < 1:
            raise ValueError("MCP server revision must be positive")
        connection = raw.get("connection")
        if not isinstance(connection, dict):
            raise ValueError("MCP server connection must be an object")
        transport = str(connection.get("transport") or "").strip()
        command = _optional_text(connection.get("command"))
        endpoint = _optional_text(connection.get("url"))
        cwd = _optional_path(connection.get("cwd"))
        timeout = float(connection.get("request_timeout_seconds", 120.0))
        connect_timeout = float(connection.get("connect_timeout_seconds", min(timeout, 30.0)))
        environment = {
            **dict(self._config.base_environment),
            **_resolved_mapping(connection.get("env"), self._environment_resolver),
        }
        headers = _resolved_mapping(connection.get("headers"), self._environment_resolver)
        binding = MCPServerRuntimeBinding(
            server_id=server_id,
            transport=transport,
            executable=command,
            arguments=tuple(str(item) for item in connection.get("args") or ()),
            endpoint=endpoint,
            working_directory=cwd,
            environment=environment,
            headers=headers,
            connect_timeout_seconds=connect_timeout,
            request_timeout_seconds=timeout,
            max_parallel_requests=int(connection.get("max_parallel_requests", 1)),
        )
        server_digest = _digest({
            "server_id": server_id,
            "revision": revision,
            "binding": {
                "transport": binding.transport,
                "executable": binding.executable,
                "arguments": binding.arguments,
                "endpoint": binding.endpoint,
                "working_directory": None if cwd is None else str(cwd),
                "environment": dict(binding.environment),
                "headers": dict(binding.headers),
                "connect_timeout_seconds": binding.connect_timeout_seconds,
                "request_timeout_seconds": binding.request_timeout_seconds,
                "max_parallel_requests": binding.max_parallel_requests,
            },
        })
        return server_id, binding, server_digest

    def _project_tools(
        self,
        raw: dict[str, Any],
        server_digest: str,
        catalog: MCPServerCatalog,
    ) -> tuple[MCPGatewayTool, ...]:
        server_id = str(raw["server_id"])
        revision = int(raw["revision"])
        defaults = raw.get("defaults") if isinstance(raw.get("defaults"), dict) else {}
        overrides = raw.get("tools") if isinstance(raw.get("tools"), dict) else {}
        prefix = str(defaults.get("tool_id_prefix") or server_id)
        if not prefix.startswith("mcp_"):
            prefix = f"mcp_{prefix}"
        aliases: set[str] = set()
        upstream_names: set[str] = set()
        projected: list[MCPGatewayTool] = []
        for upstream in sorted(catalog.tools, key=lambda item: str(item.name)):
            upstream_name = str(upstream.name)
            alias = _model_alias(f"{prefix}_{upstream_name}")
            if upstream_name in upstream_names or alias in aliases:
                raise ValueError(f"MCP server exposes duplicate or colliding tool names: {server_id}")
            upstream_names.add(upstream_name)
            aliases.add(alias)
            override = overrides.get(upstream_name) if isinstance(overrides.get(upstream_name), dict) else {}
            base_policy = ToolRuntimePolicy(
                risk_level=str(defaults.get("risk_level") or "medium"),
                allow_parallel_calls=bool(defaults.get("allow_parallel_calls", True)),
                max_parallel_calls=(
                    int(raw["connection"].get("max_parallel_requests", 1))
                    if bool(defaults.get("allow_parallel_calls", True))
                    else 1
                ),
            )
            runtime_policy = ToolRuntimePolicy.model_validate({
                **base_policy.model_dump(mode="json"),
                **dict(override.get("runtime_policy") or {}),
            })
            description = str(
                override.get("description")
                or upstream.description
                or f"MCP tool {upstream_name}"
            ).strip()
            definition = MCPToolDefinition(
                server_id=server_id,
                server_content_digest=server_digest,
                upstream_tool_name=upstream_name,
                model_alias=alias,
                model_description=description,
                input_schema=_schema_evidence(
                    upstream.input_schema if upstream.input_schema is not None else {"type": "object"}
                ),
                output_schema=_schema_evidence(
                    upstream.output_schema
                    if upstream.output_schema is not None
                    else {"type": "object", "additionalProperties": True}
                ),
                runtime_policy=runtime_policy,
                effects=("network",),
            )
            capability_id = f"mcp-tool://{server_id}/{quote(upstream_name, safe='')}"
            projected.append(MCPGatewayTool(
                capability_id=capability_id,
                server_id=server_id,
                server_revision=revision,
                display_name=str(override.get("display_name") or upstream.title or upstream_name).strip(),
                description=description,
                definition=definition,
                content_digest=_digest(definition.model_dump(mode="json")),
            ))
        return tuple(projected)

    def _commit_registry_change(
        self,
        current: dict[str, Any],
        replacement: dict[str, Any],
        prepared: MCPGatewayPreparedServer,
    ) -> None:
        changed = False
        try:
            write_mcp_gateway_registry(self.registry_path, replacement)
            changed = True
            self.synchronize()
        except BaseException:
            if changed:
                write_mcp_gateway_registry(self.registry_path, current)
            try:
                self.synchronize()
            except BaseException:
                if prepared.runtime_registered:
                    self._runtime.unregister(prepared.server.server_digest)
            raise

    @staticmethod
    def _require_registry_digest(document: dict[str, Any], expected: str) -> None:
        if _digest(document) != str(expected or "").strip():
            raise RuntimeError("mcp_registry_revision_conflict")


def empty_mcp_gateway_registry() -> dict[str, Any]:
    return {"version": MCP_GATEWAY_REGISTRY_VERSION, "revision": 1, "servers": []}


def read_mcp_gateway_registry(path: Path) -> dict[str, Any]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("version") != MCP_GATEWAY_REGISTRY_VERSION:
        raise ValueError(f"MCP registry must use {MCP_GATEWAY_REGISTRY_VERSION}")
    if int(document.get("revision") or 0) < 1:
        raise ValueError("MCP registry revision must be positive")
    servers = document.get("servers")
    if not isinstance(servers, list) or any(not isinstance(item, dict) for item in servers):
        raise ValueError("MCP registry servers must be an array of objects")
    identities = [str(item.get("server_id") or "") for item in servers]
    if len(identities) != len(set(identities)):
        raise ValueError("MCP registry server IDs must be unique")
    return document


def write_mcp_gateway_registry(path: Path, document: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _schema_evidence(schema: Any) -> MCPSchemaEvidence:
    canonical, repairs = _normalize_mcp_schema(schema)
    status = "normalized" if repairs else "valid"
    note = None
    try:
        Draft202012Validator.check_schema(canonical)
    except SchemaError as exc:
        degraded = {"type": "object", "additionalProperties": True}
        repairs = (*repairs, MCPSchemaRepairRecord(
            path="/",
            original_digest=_digest(canonical),
            replacement_digest=_digest(degraded),
            reason="replaced an invalid upstream schema with a permissive object schema",
        ))
        canonical = degraded
        status = "degraded"
        note = str(exc.message or "invalid upstream JSON Schema")
    return MCPSchemaEvidence(
        dialect="mcp_unspecified",
        source_schema=schema,
        source_digest=_digest(schema),
        normalization_receipt=repairs,
        canonical_schema=canonical,
        canonical_digest=_digest(canonical),
        compatibility_status=status,
        compatibility_note=note,
    )


def _normalize_mcp_schema(schema: Any) -> tuple[dict[str, Any], tuple[MCPSchemaRepairRecord, ...]]:
    repairs: list[MCPSchemaRepairRecord] = []
    canonical = _normalize_schema_node(schema, path=(), repairs=repairs)
    if not isinstance(canonical, dict):
        replacement = {"type": "object", "additionalProperties": True}
        repairs.append(MCPSchemaRepairRecord(
            path="/",
            original_digest=_digest(canonical),
            replacement_digest=_digest(replacement),
            reason="replaced a non-object schema root with a permissive object schema",
        ))
        canonical = replacement
    return canonical, tuple(repairs)


def _normalize_schema_node(value: Any, *, path: tuple[str, ...], repairs: list[MCPSchemaRepairRecord]) -> Any:
    if isinstance(value, bool):
        replacement = {"type": "object", "additionalProperties": True}
        repairs.append(MCPSchemaRepairRecord(
            path=_json_pointer(path),
            original_digest=_digest(value),
            replacement_digest=_digest(replacement),
            reason="projected a boolean schema into the object-shaped model tool contract",
        ))
        return replacement
    if isinstance(value, str) and value in _JSON_SCHEMA_TYPES:
        replacement = {"type": value}
        repairs.append(MCPSchemaRepairRecord(
            path=_json_pointer(path),
            original_digest=_digest(value),
            replacement_digest=_digest(replacement),
            reason="expanded JSON type shorthand into a schema object",
        ))
        return replacement
    if not isinstance(value, dict):
        return value
    normalized: dict[str, Any] = {}
    for raw_key, item in value.items():
        key = str(raw_key)
        item_path = (*path, key)
        if key in _SCHEMA_VALUE_KEYWORDS:
            normalized[key] = _normalize_schema_node(item, path=item_path, repairs=repairs)
        elif key == "items":
            normalized[key] = (
                [_normalize_schema_node(child, path=(*item_path, str(index)), repairs=repairs) for index, child in enumerate(item)]
                if isinstance(item, list)
                else _normalize_schema_node(item, path=item_path, repairs=repairs)
            )
        elif key in _SCHEMA_ARRAY_KEYWORDS and isinstance(item, list):
            normalized[key] = [
                _normalize_schema_node(child, path=(*item_path, str(index)), repairs=repairs)
                for index, child in enumerate(item)
            ]
        elif key in _SCHEMA_MAP_KEYWORDS and isinstance(item, dict):
            normalized[key] = {
                str(name): _normalize_schema_node(child, path=(*item_path, str(name)), repairs=repairs)
                for name, child in item.items()
            }
        elif key == "dependencies" and isinstance(item, dict):
            normalized[key] = {
                str(name): child if isinstance(child, list) else _normalize_schema_node(
                    child, path=(*item_path, str(name)), repairs=repairs
                )
                for name, child in item.items()
            }
        else:
            normalized[key] = item
    return normalized


def _resolved_mapping(value: Any, resolver: Callable[[str], str | None]) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("MCP environment and headers must be mappings")
    resolved: dict[str, str] = {}
    for key, item in value.items():
        name = str(key).strip()
        if not name:
            raise ValueError("MCP environment and header names must not be empty")
        if isinstance(item, str):
            resolved[name] = item
            continue
        if not isinstance(item, dict):
            raise ValueError("MCP environment and header values must be strings or value sources")
        source = str(item.get("source") or "").strip()
        if source == "literal":
            resolved[name] = str(item.get("value") or "")
        elif source == "process_environment":
            source_name = str(item.get("name") or "").strip()
            source_value = resolver(source_name) if source_name else None
            if source_value is None:
                raise RuntimeError(f"required MCP process environment value is unavailable: {source_name}")
            resolved[name] = source_value
        else:
            raise ValueError("unsupported MCP environment or header value source")
    return resolved


def _model_alias(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")
    if not normalized or not normalized[0].isalpha():
        normalized = f"mcp_{normalized}"
    if len(normalized) > 64:
        suffix = sha256(normalized.encode("utf-8")).hexdigest()[:8]
        normalized = f"{normalized[:55]}_{suffix}"
    return normalized


def _json_pointer(path: tuple[str, ...]) -> str:
    if not path:
        return "/"
    return "/" + "/".join(part.replace("~", "~0").replace("/", "~1") for part in path)


def _progress(
    callback: Callable[[str, dict[str, Any]], None] | None,
    stage: str,
    server_id: str,
    detail: dict[str, Any],
) -> None:
    if callback is not None:
        callback(stage, {"server_id": server_id, **detail})


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_path(value: Any) -> Path | None:
    text = _optional_text(value)
    return None if text is None else Path(text).expanduser().resolve()


def _normalized_name(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def _required_text(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text
