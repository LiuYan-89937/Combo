from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Callable
from urllib.parse import quote

from agent_factory.dynamic_runtime.capability_definitions import (
    MCPSchemaEvidence,
    MCPServerDefinition,
    MCPToolDefinition,
    ToolRuntimePolicy,
)
from agent_factory.dynamic_runtime.mcp_runtime import MCPRuntimePool, MCPServerRuntimeBinding
from agent_factory.runtime_protocol import CapabilityContent, CapabilityDependencyRef, CapabilityDraft


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


@dataclass(frozen=True, slots=True)
class MCPConfigSourceConfig:
    path: Path
    publisher_principal_id: str
    source_prefix: str
    base_environment: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path).expanduser().resolve())
        if not self.publisher_principal_id.strip() or not self.source_prefix.strip():
            raise ValueError("MCP config source requires publisher and source prefix")


class MCPConfigCapabilitySource:
    """Discover configured MCP servers and project them into the shared capability pool."""

    def __init__(
        self,
        *,
        config: MCPConfigSourceConfig,
        runtime: MCPRuntimePool,
        environment_resolver: Callable[[str], str | None],
        report_unavailable: Callable[[str, BaseException], None],
    ) -> None:
        self._config = config
        self._runtime = runtime
        self._environment_resolver = environment_resolver
        self._report_unavailable = report_unavailable

    def drafts(self) -> tuple[CapabilityDraft, ...]:
        document = json.loads(self._config.path.read_text(encoding="utf-8"))
        if document.get("version") != "mcp_servers.v0" or not isinstance(document.get("servers"), list):
            raise ValueError("MCP server registry must use mcp_servers.v0")
        drafts: list[CapabilityDraft] = []
        for raw in document["servers"]:
            if not isinstance(raw, dict) or not raw.get("enabled", True):
                continue
            try:
                server_draft, binding = self._server_draft(raw)
                self._runtime.register(server_draft.content_digest, binding)
                tools = self._runtime.discover_tools(server_draft.content_digest)
            except Exception as exc:
                server_id = str(raw.get("server_id") or "").strip() or "<invalid>"
                self._report_unavailable(server_id, exc)
                if raw.get("required", False):
                    raise
                continue
            drafts.append(server_draft)
            drafts.extend(self._tool_drafts(raw, server_draft, tools))
        return tuple(drafts)

    def _server_draft(self, raw: dict[str, Any]) -> tuple[CapabilityDraft, MCPServerRuntimeBinding]:
        server_id = str(raw.get("server_id") or "").strip()
        if not _IDENTIFIER.fullmatch(server_id):
            raise ValueError("MCP server_id must be a stable lowercase identifier")
        transport = str(raw.get("transport") or "").strip()
        command = _optional_text(raw.get("command"))
        endpoint = _optional_text(raw.get("url"))
        cwd = _optional_path(raw.get("cwd"))
        timeout = float(raw.get("timeout_seconds", 120.0))
        definition = MCPServerDefinition(
            transport=transport,
            executable=command,
            arguments=tuple(str(item) for item in raw.get("args") or ()),
            endpoint=endpoint,
            working_directory_alias=server_id if cwd is not None else None,
            connect_timeout_seconds=min(timeout, 30.0),
            request_timeout_seconds=timeout,
            max_parallel_requests=int(raw.get("max_parallel_requests", 1)),
        )
        source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
        environment = {
            **dict(self._config.base_environment),
            **_resolved_mapping(raw.get("env"), self._environment_resolver),
        }
        headers = _resolved_mapping(raw.get("headers"), self._environment_resolver)
        runtime_fingerprint = _digest(
            {
                "definition": definition.model_dump(mode="json"),
                "cwd": None if cwd is None else str(cwd),
                "environment": environment,
                "headers": headers,
            }
        )
        draft = CapabilityDraft(
            capability_id=f"mcp-server://{server_id}",
            kind="mcp_server",
            draft_revision=1,
            namespace=f"mcp.{server_id}",
            resolved_version=runtime_fingerprint,
            source_uri=f"{self._config.source_prefix}{server_id}/{runtime_fingerprint}",
            trust_level="builtin" if source.get("kind") == "builtin" else "local_user",
            content=CapabilityContent(
                display_name=str(source.get("name") or server_id),
                description=str(source.get("description") or f"MCP server {server_id}"),
                keywords=("mcp", server_id),
                definition_schema="mcp_server_definition.v1",
                definition=definition.model_dump(mode="json"),
            ),
            updated_by_principal_id=self._config.publisher_principal_id,
        )
        binding = MCPServerRuntimeBinding(
            transport=definition.transport,
            executable=definition.executable,
            arguments=definition.arguments,
            endpoint=definition.endpoint,
            working_directory=cwd,
            environment=environment,
            headers=headers,
            connect_timeout_seconds=definition.connect_timeout_seconds,
            request_timeout_seconds=definition.request_timeout_seconds,
            max_parallel_requests=definition.max_parallel_requests,
        )
        return draft, binding

    def _tool_drafts(
        self,
        raw: dict[str, Any],
        server: CapabilityDraft,
        tools: tuple[Any, ...],
    ) -> tuple[CapabilityDraft, ...]:
        server_id = server.namespace.removeprefix("mcp.")
        prefix = str(raw.get("tool_id_prefix") or server_id)
        if not prefix.startswith("mcp_"):
            prefix = f"mcp_{prefix}"
        risk = str(raw.get("risk_level_default") or "medium")
        concurrent = bool(raw.get("concurrent_default", True))
        result: list[CapabilityDraft] = []
        aliases: set[str] = set()
        upstream_names: set[str] = set()
        for tool in sorted(tools, key=lambda item: str(item.name)):
            upstream_name = str(tool.name)
            alias = _model_alias(f"{prefix}_{upstream_name}")
            if upstream_name in upstream_names or alias in aliases:
                raise ValueError(f"MCP server exposes duplicate or colliding tool names: {server_id}")
            upstream_names.add(upstream_name)
            aliases.add(alias)
            input_schema = dict(tool.inputSchema or {"type": "object"})
            output_schema = dict(tool.outputSchema or {"type": "object", "additionalProperties": True})
            definition = MCPToolDefinition(
                server_capability_id=server.capability_id,
                upstream_tool_name=upstream_name,
                model_alias=alias,
                model_description=str(tool.description or f"MCP tool {upstream_name}"),
                input_schema=_schema_evidence(input_schema),
                output_schema=_schema_evidence(output_schema),
                runtime_policy=ToolRuntimePolicy(
                    risk_level=risk,
                    allow_parallel_calls=concurrent,
                    max_parallel_calls=server.content.definition["max_parallel_requests"],
                ),
                effects=("network",),
            )
            result.append(
                CapabilityDraft(
                    capability_id=f"mcp-tool://{server_id}/{quote(upstream_name, safe='')}",
                    kind="mcp_tool",
                    draft_revision=1,
                    namespace=f"mcp.{server_id}.{alias}",
                    resolved_version=_digest(definition.model_dump(mode="json")),
                    source_uri=(
                        f"{self._config.source_prefix}{server_id}/tools/"
                        f"{quote(upstream_name, safe='')}"
                    ),
                    trust_level=server.trust_level,
                    content=CapabilityContent(
                        display_name=alias,
                        description=definition.model_description,
                        keywords=("mcp", server_id, upstream_name),
                        definition_schema="mcp_tool_definition.v2",
                        definition=definition.model_dump(mode="json"),
                        dependencies=(
                            CapabilityDependencyRef(
                                capability_id=server.capability_id,
                                kind="mcp_server",
                                version_constraint=f"={server.resolved_version}",
                            ),
                        ),
                    ),
                    updated_by_principal_id=self._config.publisher_principal_id,
                )
            )
        return tuple(result)


def _schema_evidence(schema: dict[str, Any]) -> MCPSchemaEvidence:
    digest = _digest(schema)
    return MCPSchemaEvidence(
        dialect="mcp_unspecified",
        source_schema=schema,
        source_digest=digest,
        canonical_schema=schema,
        canonical_digest=digest,
    )


def _digest(value: Any) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(serialized.encode("utf-8")).hexdigest()


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_path(value: Any) -> Path | None:
    text = _optional_text(value)
    return None if text is None else Path(text).expanduser().resolve()


def _resolved_mapping(
    value: Any,
    environment_resolver: Callable[[str], str | None],
) -> dict[str, str]:
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
            continue
        if source != "process_environment":
            raise ValueError("unsupported MCP environment or header value source")
        source_name = str(item.get("name") or "").strip()
        if not source_name:
            raise ValueError("MCP process environment value source requires a name")
        source_value = environment_resolver(source_name)
        if source_value is None:
            raise RuntimeError(f"required MCP process environment value is unavailable: {source_name}")
        resolved[name] = source_value
    return resolved


def _model_alias(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")
    if not normalized or not normalized[0].isalpha():
        normalized = f"mcp_{normalized}"
    if len(normalized) > 64:
        suffix = sha256(normalized.encode("utf-8")).hexdigest()[:8]
        normalized = f"{normalized[:55]}_{suffix}"
    return normalized
