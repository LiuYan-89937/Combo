from __future__ import annotations

from hashlib import sha256
import json
from typing import Any
from urllib.parse import quote

from combo.dynamic_runtime.application import DynamicRuntimeApplication
from combo.dynamic_runtime.capability_definitions import MCPToolDefinition, SkillDefinition, ToolDefinition
from combo.dynamic_runtime.capability_search import ActiveVectorIndexStatus
from combo.dynamic_runtime.delegation_policy import TEMPORARY_RUNTIME_ONLY_CAPABILITY_IDS
from combo.dynamic_runtime.mcp_gateway import MCPGateway
from combo.dynamic_runtime.mcp_runtime import MCPRuntimePool
from combo.dynamic_runtime.skill_source import SkillSourceRoot
from combo.dynamic_runtime.tool_package_source import ToolSourceRoot


class CapabilityPoolView:
    """Project the current capability sources for desktop clients."""

    def __init__(
        self,
        *,
        application: DynamicRuntimeApplication,
        skill_source_roots: tuple[SkillSourceRoot, ...],
        tool_source_roots: tuple[ToolSourceRoot, ...],
        mcp_gateway: MCPGateway,
        mcp_runtime: MCPRuntimePool,
    ) -> None:
        self.application = application
        self.skill_source_roots = skill_source_roots
        self.tool_source_roots = tool_source_roots
        self.mcp_gateway = mcp_gateway
        self.mcp_runtime = mcp_runtime

    def snapshot(self) -> dict[str, object]:
        capabilities: list[dict[str, object]] = []
        counts = {"skill": 0, "tool": 0, "mcp_server": 0, "mcp_tool": 0}
        vector_index = self.application.capability_search.active_vector_index_status()
        for item in self.application.stores.capabilities.active_capabilities():
            revision = item.revision
            if revision.kind not in counts:
                continue
            if revision.capability_id in TEMPORARY_RUNTIME_ONLY_CAPABILITY_IDS:
                continue
            counts[revision.kind] += 1
            health = self.application.stores.capability_resolution_receipts.latest_health(
                capability_id=revision.capability_id,
                revision=revision.revision,
                content_digest=revision.content_digest,
            )
            details = _capability_public_details(revision.kind, revision.content.definition)
            if revision.kind == "skill":
                skill_parts = revision.capability_id.removeprefix("skill://").split("/", 1)
                if len(skill_parts) == 2:
                    source_root = next(
                        (root for root in self.skill_source_roots if root.root_id == skill_parts[0]),
                        None,
                    )
                    if source_root is not None:
                        details["source_path"] = str(source_root.path / skill_parts[1])
            if revision.kind == "tool" and revision.trust_level == "local_user":
                tool_parts = revision.capability_id.removeprefix("tool://").split("/", 1)
                if len(tool_parts) == 2:
                    source_root = next(
                        (root for root in self.tool_source_roots if root.root_id == tool_parts[0]),
                        None,
                    )
                    if source_root is not None:
                        details["source_path"] = str(source_root.path / tool_parts[1])
            capabilities.append(
                {
                    "capability_id": revision.capability_id,
                    "kind": revision.kind,
                    "namespace": revision.namespace,
                    "display_name": revision.content.display_name,
                    "description": revision.content.description,
                    "keywords": list(revision.content.keywords),
                    "revision": revision.revision,
                    "resolved_version": revision.resolved_version,
                    "content_digest": revision.content_digest,
                    "source_uri": revision.source_uri,
                    "trust_level": revision.trust_level,
                    "health": None if health is None else health.status,
                    "indexing": {
                        "vector": (
                            vector_index is not None
                            and revision.capability_id in vector_index.capability_ids
                        ),
                        "generation_id": (
                            vector_index.generation_id if vector_index is not None else None
                        ),
                        "embedding_profile_id": (
                            vector_index.profile_id if vector_index is not None else None
                        ),
                    },
                    "definition_schema": revision.content.definition_schema,
                    "details": details,
                }
            )
        gateway_items = self._mcp_gateway_capability_items(vector_index)
        capabilities.extend(gateway_items)
        counts["mcp_server"] = sum(item["kind"] == "mcp_server" for item in gateway_items)
        counts["mcp_tool"] = sum(item["kind"] == "mcp_tool" for item in gateway_items)
        capabilities.sort(key=lambda value: (str(value["kind"]), str(value["namespace"])))
        return {
            "counts": counts,
            "capabilities": capabilities,
            "mcp_registry_digest": self.mcp_gateway.registry_digest(),
        }

    def _mcp_gateway_capability_items(
        self,
        vector_index: ActiveVectorIndexStatus | None,
    ) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        connected_ids = {server.server_id for server in self.mcp_gateway.servers()}
        for raw in self.mcp_gateway.registry()["servers"]:
            server_id = str(raw.get("server_id") or "").strip()
            if server_id in connected_ids:
                continue
            content_digest = _stable_json_digest(raw)
            items.append({
                "capability_id": f"mcp-server://{server_id}",
                "kind": "mcp_server",
                "namespace": f"mcp.{server_id}",
                "display_name": str(raw.get("display_name") or server_id),
                "description": str(raw.get("description") or ""),
                "keywords": ["mcp", server_id],
                "revision": int(raw.get("revision") or 1),
                "resolved_version": content_digest,
                "content_digest": content_digest,
                "source_uri": f"mcp-gateway://{server_id}",
                "trust_level": "local_user",
                "health": "unavailable",
                "indexing": {"vector": False, "generation_id": None, "embedding_profile_id": None},
                "definition_schema": "mcp_gateway_server.v1",
                "details": {
                    "registry_config": _mcp_server_editor_config(raw),
                    "connection_status": "unavailable",
                    "transport": dict(raw.get("connection") or {}).get("transport"),
                    "tool_count": 0,
                    "resource_count": 0,
                    "resource_template_count": 0,
                    "prompt_count": 0,
                    "resources": [],
                    "resource_templates": [],
                    "prompts": [],
                    "logs": [],
                },
            })
        for server in self.mcp_gateway.servers():
            catalog = server.catalog
            items.append({
                "capability_id": f"mcp-server://{server.server_id}",
                "kind": "mcp_server",
                "namespace": f"mcp.{server.server_id}",
                "display_name": str(server.raw_config.get("display_name") or server.server_id),
                "description": str(server.raw_config.get("description") or ""),
                "keywords": ["mcp", server.server_id],
                "revision": server.revision,
                "resolved_version": server.server_digest,
                "content_digest": server.server_digest,
                "source_uri": f"mcp-gateway://{server.server_id}",
                "trust_level": "local_user",
                "health": "healthy",
                "indexing": {
                    "vector": (
                        vector_index is not None
                        and f"mcp-server://{server.server_id}" in vector_index.capability_ids
                    ),
                    "generation_id": (
                        vector_index.generation_id if vector_index is not None else None
                    ),
                    "embedding_profile_id": (
                        vector_index.profile_id if vector_index is not None else None
                    ),
                },
                "definition_schema": "mcp_gateway_server.v1",
                "details": {
                    "registry_config": _mcp_server_editor_config(server.raw_config),
                    "connection_status": "connected",
                    "transport": server.raw_config["connection"]["transport"],
                    "protocol_version": catalog.protocol_version,
                    "server_name": catalog.server_name,
                    "server_version": catalog.server_version,
                    "server_title": catalog.server_title,
                    "server_instructions": catalog.server_instructions,
                    "server_capabilities": list(catalog.capabilities),
                    "tool_count": len(server.tools),
                    "resource_count": len(catalog.resources),
                    "resource_template_count": len(catalog.resource_templates),
                    "prompt_count": len(catalog.prompts),
                    "resources": [_mcp_resource_view(value) for value in catalog.resources],
                    "resource_templates": [_mcp_resource_template_view(value) for value in catalog.resource_templates],
                    "prompts": [_mcp_prompt_view(value) for value in catalog.prompts],
                    "logs": list(self.mcp_runtime.logs(server.server_id)),
                },
            })
            for tool in server.tools:
                definition = tool.definition
                items.append({
                    "capability_id": tool.capability_id,
                    "kind": "mcp_tool",
                    "namespace": f"mcp.{server.server_id}.{definition.model_alias}",
                    "display_name": tool.display_name,
                    "description": tool.description,
                    "keywords": ["mcp", server.server_id, definition.upstream_tool_name],
                    "revision": tool.server_revision,
                    "resolved_version": definition.server_content_digest,
                    "content_digest": tool.content_digest,
                    "source_uri": f"mcp-gateway://{server.server_id}/tools/{quote(definition.upstream_tool_name, safe='')}",
                    "trust_level": "local_user",
                    "health": "healthy",
                    "indexing": {"vector": False, "generation_id": None, "embedding_profile_id": None},
                    "definition_schema": "mcp_tool_definition.v3",
                    "details": _mcp_tool_public_details(definition),
                })
        return items


def _capability_public_details(kind: str, raw_definition: dict[str, Any]) -> dict[str, object]:
    if kind == "skill":
        definition = SkillDefinition.model_validate(raw_definition)
        contents = (definition.instructions, *definition.contents)
        return {
            "content_count": len(contents),
            "total_size_bytes": sum(item.size_bytes for item in contents),
            "content_paths": [item.logical_path for item in contents],
        }
    if kind == "tool":
        definition = ToolDefinition.model_validate(raw_definition)
        return {
            "model_alias": definition.model_alias,
            "approval": definition.runtime_policy.approval,
            "risk_level": definition.runtime_policy.risk_level,
            "allow_parallel_calls": definition.runtime_policy.allow_parallel_calls,
            "max_parallel_calls": definition.runtime_policy.max_parallel_calls,
            "timeout_seconds": definition.runtime_policy.timeout_seconds,
            "output_projection": definition.runtime_policy.output_projection,
            "output_max_model_chars": definition.runtime_policy.output_max_model_chars,
            "retain_raw_output": definition.runtime_policy.retain_raw_output,
            "read_only": definition.read_only,
            "input_schema": definition.input_schema,
            "context_schema": definition.context_schema,
            "system_available": definition.system_available,
            "effects": list(definition.effects),
            "implementation_kind": definition.implementation.kind,
            "package_file_count": len(definition.implementation.package_files),
            "python_requirements": list(definition.implementation.python_requirements),
        }
    return {}


def _mcp_tool_public_details(definition: MCPToolDefinition) -> dict[str, object]:
    return {
        "server_id": definition.server_id,
        "upstream_tool_name": definition.upstream_tool_name,
        "model_alias": definition.model_alias,
        "approval": definition.runtime_policy.approval,
        "risk_level": definition.runtime_policy.risk_level,
        "allow_parallel_calls": definition.runtime_policy.allow_parallel_calls,
        "max_parallel_calls": definition.runtime_policy.max_parallel_calls,
        "timeout_seconds": definition.runtime_policy.timeout_seconds,
        "output_projection": definition.runtime_policy.output_projection,
        "output_max_model_chars": definition.runtime_policy.output_max_model_chars,
        "retain_raw_output": definition.runtime_policy.retain_raw_output,
        "effects": list(definition.effects),
        "input_schema_digest": definition.input_schema.canonical_digest,
        "output_schema_digest": definition.output_schema.canonical_digest,
        "input_schema_status": definition.input_schema.compatibility_status,
        "output_schema_status": definition.output_schema.compatibility_status,
        "schema_degraded": (
            definition.input_schema.compatibility_status == "degraded"
            or definition.output_schema.compatibility_status == "degraded"
        ),
    }


def _mcp_server_editor_config(document: dict[str, Any]) -> dict[str, object]:
    connection = dict(document.get("connection") or {})
    defaults = dict(document.get("defaults") or {})
    return {
        "server_id": document.get("server_id"),
        "display_name": document.get("display_name"),
        "description": document.get("description"),
        "enabled": document.get("enabled", True),
        "transport": connection.get("transport"),
        "command": connection.get("command"),
        "args": connection.get("args", []),
        "cwd": connection.get("cwd"),
        "url": connection.get("url"),
        "env": connection.get("env", {}),
        "headers": connection.get("headers", {}),
        "connect_timeout_seconds": connection.get("connect_timeout_seconds", 30),
        "timeout_seconds": connection.get("request_timeout_seconds", 120),
        "max_parallel_requests": connection.get("max_parallel_requests", 1),
        "risk_level_default": defaults.get("risk_level", "medium"),
        "concurrent_default": defaults.get("allow_parallel_calls", True),
    }


def _mcp_resource_view(item: Any) -> dict[str, object]:
    return {
        "name": str(getattr(item, "name", "")),
        "title": getattr(item, "title", None),
        "description": str(getattr(item, "description", "") or ""),
        "uri": str(getattr(item, "uri", "")),
        "mime_type": str(getattr(item, "mime_type", "") or ""),
        "size": getattr(item, "size", None),
        "icons": [icon.model_dump(mode="json", exclude_none=True) for icon in (item.icons or ())],
        "annotations": item.annotations.model_dump(mode="json", exclude_none=True) if item.annotations else None,
    }


def _mcp_resource_template_view(item: Any) -> dict[str, object]:
    return {
        "name": str(getattr(item, "name", "")),
        "title": getattr(item, "title", None),
        "description": str(getattr(item, "description", "") or ""),
        "uri_template": str(getattr(item, "uri_template", "")),
        "mime_type": str(getattr(item, "mime_type", "") or ""),
        "icons": [icon.model_dump(mode="json", exclude_none=True) for icon in (item.icons or ())],
        "annotations": item.annotations.model_dump(mode="json", exclude_none=True) if item.annotations else None,
    }


def _mcp_prompt_view(item: Any) -> dict[str, object]:
    return {
        "name": str(getattr(item, "name", "")),
        "title": getattr(item, "title", None),
        "description": str(getattr(item, "description", "") or ""),
        "arguments": [
            {
                "name": str(getattr(argument, "name", "")),
                "description": str(getattr(argument, "description", "") or ""),
                "required": bool(getattr(argument, "required", False)),
            }
            for argument in (getattr(item, "arguments", ()) or ())
        ],
        "icons": [icon.model_dump(mode="json", exclude_none=True) for icon in (item.icons or ())],
    }


def _stable_json_digest(value: object) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(serialized.encode("utf-8")).hexdigest()

