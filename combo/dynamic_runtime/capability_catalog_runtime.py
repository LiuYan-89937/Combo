from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import TypeVar

from combo.dynamic_runtime.capability_resolution_store import CapabilityResolutionReceiptStore
from combo.dynamic_runtime.capability_definitions import SkillDefinition, ToolDefinition
from combo.dynamic_runtime.capability_resolver import CapabilitySearchIndex
from combo.dynamic_runtime.capability_search_documents import (
    search_candidates_from_active_capabilities,
)
from combo.dynamic_runtime.capability_store import ActiveCapability, CapabilityStore
from combo.dynamic_runtime.delegation_policy import capability_is_delegatable
from combo.dynamic_runtime.mcp_gateway import (
    MCPGateway,
    MCPGatewayCatalogEntry,
    MCPGatewayServer,
)
from combo.runtime_protocol import CapabilityTrustLevel


@dataclass(frozen=True, slots=True)
class CapabilityInvocationTarget:
    capability_id: str
    kind: str
    public_name: str
    server_id: str | None = None


class CapabilityCatalogRuntime:
    """Read-only control-plane view used by the stable main-agent capability tool."""

    def __init__(
        self,
        *,
        store: CapabilityStore,
        health_receipts: CapabilityResolutionReceiptStore,
        allowed_trust_levels: tuple[CapabilityTrustLevel, ...],
        search_index: CapabilitySearchIndex,
        mcp_gateway: MCPGateway,
    ) -> None:
        if not allowed_trust_levels:
            raise ValueError("capability catalog requires allowed trust levels")
        self._store = store
        self._health_receipts = health_receipts
        self._allowed_trust_levels = frozenset(allowed_trust_levels)
        self._search_index = search_index
        self._mcp_gateway = mcp_gateway

    def list_active(self) -> list[dict[str, object]]:
        return [
            *(self._summary(item) for item in self._eligible()),
            *(self._mcp_summary(server) for server in self._mcp_gateway.servers()),
        ]

    def active_skills(self) -> tuple[ActiveCapability, ...]:
        """Return the same active Skill surface that top-level search can disclose."""
        return tuple(item for item in self._eligible() if item.revision.kind == "skill")

    def search(self, query: str, *, limit: int) -> list[dict[str, object]]:
        normalized = str(query or "").strip()
        if not normalized:
            raise ValueError("capability search query must not be empty")
        if limit < 1:
            raise ValueError("capability search limit must be positive")
        eligible = self._eligible()
        by_id = {item.revision.capability_id: item for item in eligible}
        mcp_by_id = self._mcp_by_id()
        candidates = (
            *search_candidates_from_active_capabilities(eligible),
            *self._mcp_gateway.server_search_candidates(),
        )
        matches = self._search_index.search(requirements=(normalized,), candidates=candidates)
        results: list[dict[str, object]] = []
        for match in matches[:limit]:
            if match.capability_id in by_id:
                summary = self._summary(by_id[match.capability_id])
            elif match.capability_id in mcp_by_id:
                summary = self._mcp_summary(mcp_by_id[match.capability_id])
            else:
                continue
            results.append({
                **summary,
                "retrieval": {
                    "channels": list(match.retrieval_channels),
                    "matched_fields": list(match.matched_fields),
                },
            })
        return results

    def search_mcp(
        self,
        server_name: str,
        query: str,
        *,
        kinds: tuple[str, ...],
        limit: int,
    ) -> list[dict[str, object]]:
        server = self._resolve_mcp_server(server_name)
        normalized_query = _required_text(query, "query")
        if limit < 1:
            raise ValueError("MCP catalog search limit must be positive")
        normalized_kinds = tuple(dict.fromkeys(_required_text(value, "kind") for value in kinds))
        entries = self._mcp_gateway.catalog_entries(server.server_id)
        if normalized_kinds:
            allowed = frozenset(normalized_kinds)
            entries = tuple(item for item in entries if item.kind in allowed)
        candidates = tuple(item.search_candidate() for item in entries)
        by_id = {item.capability_id: item for item in entries}
        matches = self._search_index.search(
            requirements=(normalized_query,),
            candidates=candidates,
        )
        results: list[dict[str, object]] = []
        for match in matches[:limit]:
            entry = by_id.get(match.capability_id)
            if entry is None:
                continue
            results.append({
                **self._mcp_entry_summary(server, entry),
                "retrieval": {
                    "channels": list(match.retrieval_channels),
                    "matched_fields": list(match.matched_fields),
                },
            })
        return results

    def describe(
        self,
        *,
        name: str,
        kind: str | None = None,
        server_name: str | None = None,
    ) -> dict[str, object]:
        requested_name = _required_text(name, "name")
        requested_kind = None if kind is None else _required_text(kind, "kind")
        if server_name is not None:
            server = self._resolve_mcp_server(server_name)
            matches = tuple(
                entry
                for entry in self._mcp_gateway.catalog_entries(server.server_id)
                if _matches_public_name(entry, requested_name)
                and (requested_kind is None or entry.kind == requested_kind)
            )
            entry = _require_unique_match(matches, requested_name)
            return {
                **self._mcp_entry_summary(server, entry),
                "definition": entry.descriptor,
            }

        top_level: list[tuple[str, ActiveCapability | MCPGatewayServer]] = []
        for item in self._eligible():
            if _matches_active_capability(item, requested_name):
                top_level.append((item.revision.kind, item))
        for server in self._mcp_gateway.servers():
            if _matches_mcp_server(server, requested_name):
                top_level.append(("mcp_server", server))
        if requested_kind is not None:
            top_level = [item for item in top_level if item[0] == requested_kind]
        _, selected = _require_unique_match(tuple(top_level), requested_name)
        if isinstance(selected, MCPGatewayServer):
            return {
                **self._mcp_summary(selected),
                "catalog": {
                    "tools": len(selected.tools),
                    "resources": len(selected.catalog.resources),
                    "resource_templates": len(selected.catalog.resource_templates),
                    "prompts": len(selected.catalog.prompts),
                },
            }
        return self._active_description(selected)

    def resolve_invocation_target(
        self,
        *,
        name: str,
        kind: str,
        server_name: str | None,
    ) -> CapabilityInvocationTarget:
        requested_kind = _required_text(kind, "kind")
        if requested_kind not in {"tool", "mcp_tool"}:
            raise ValueError("only Tool and MCP Tool capabilities can be invoked")
        requested_name = _required_text(name, "name")
        if requested_kind == "mcp_tool":
            if server_name is None:
                raise ValueError("MCP Tool invocation requires server_name")
            server = self._resolve_mcp_server(server_name)
            matches = tuple(
                entry
                for entry in self._mcp_gateway.catalog_entries(server.server_id)
                if entry.kind == "mcp_tool" and _matches_public_name(entry, requested_name)
            )
            entry = _require_unique_match(matches, requested_name)
            return CapabilityInvocationTarget(
                capability_id=entry.capability_id,
                kind="mcp_tool",
                public_name=entry.display_name,
                server_id=server.server_id,
            )
        matches = tuple(
            item
            for item in self._eligible()
            if item.revision.kind == "tool" and _matches_active_capability(item, requested_name)
        )
        item = _require_unique_match(matches, requested_name)
        return CapabilityInvocationTarget(
            capability_id=item.revision.capability_id,
            kind="tool",
            public_name=item.revision.content.display_name,
        )

    def inspect(self, capability_id: str) -> dict[str, object]:
        requested = _required_text(capability_id, "capability_id")
        external = self._mcp_by_id().get(requested)
        if external is not None:
            return {
                **self._mcp_summary(external),
                "source_uri": f"mcp-gateway://{external.server_id}",
                "resolved_version": external.server_digest,
                "dependencies": [],
                "resources": [],
                "definition_schema": "mcp_gateway_server.v1",
            }
        item = self._by_id().get(requested)
        if item is None:
            raise LookupError(f"active capability not found: {capability_id}")
        revision = item.revision
        return {
            **self._summary(item),
            "source_uri": revision.source_uri,
            "resolved_version": revision.resolved_version,
            "dependencies": [
                dependency.model_dump(mode="json")
                for dependency in revision.content.dependencies
            ],
            "resources": [resource.model_dump(mode="json") for resource in revision.content.resources],
            "definition_schema": revision.content.definition_schema,
        }

    def prepare(self, capability_ids: tuple[str, ...]) -> dict[str, object]:
        requested = tuple(dict.fromkeys(_required_text(value, "capability_id") for value in capability_ids))
        if not requested:
            raise ValueError("capability preparation requires at least one capability ID")
        active = self._by_id()
        external = self._mcp_by_id()
        selected: dict[str, ActiveCapability] = {}
        selected_external: dict[str, MCPGatewayServer] = {}
        visiting: list[str] = []

        def include(capability_id: str) -> None:
            external_server = external.get(capability_id)
            if external_server is not None:
                selected_external[capability_id] = external_server
                return
            if capability_id in selected:
                return
            item = active.get(capability_id)
            if item is None:
                raise LookupError(f"active capability not found: {capability_id}")
            if capability_id in visiting:
                start = visiting.index(capability_id)
                raise ValueError("capability dependency cycle: " + " -> ".join((*visiting[start:], capability_id)))
            health = self._health_receipts.latest_health(
                capability_id=capability_id,
                revision=item.revision.revision,
                content_digest=item.revision.content_digest,
            )
            if health is None or health.status != "healthy":
                raise RuntimeError(f"capability revision is not healthy: {capability_id}")
            if health.valid_until is not None and datetime.fromisoformat(health.valid_until) <= datetime.now(timezone.utc):
                raise RuntimeError(f"capability health receipt expired: {capability_id}")
            visiting.append(capability_id)
            try:
                for dependency in item.revision.content.dependencies:
                    if dependency.required:
                        include(dependency.capability_id)
            finally:
                visiting.pop()
            selected[capability_id] = item

        for capability_id in requested:
            include(capability_id)
        references = [
            {
                "capability_id": item.revision.capability_id,
                "kind": item.revision.kind,
                "revision": item.revision.revision,
                "resolved_version": item.revision.resolved_version,
                "content_digest": item.revision.content_digest,
            }
            for item in sorted(selected.values(), key=lambda value: value.revision.capability_id)
        ]
        references.extend(
            {
                "capability_id": f"mcp-server://{server.server_id}",
                "kind": "mcp_server",
                "revision": server.revision,
                "resolved_version": server.server_digest,
                "content_digest": server.server_digest,
            }
            for server in sorted(selected_external.values(), key=lambda value: value.server_id)
        )
        return {
            "requested_capability_ids": list(requested),
            "capability_revisions": references,
            "preparation_digest": _digest(references),
        }

    def _eligible(self) -> tuple[ActiveCapability, ...]:
        return tuple(
            item
            for item in self._store.active_capabilities()
            if item.revision.trust_level in self._allowed_trust_levels
            and _delegatable(item)
            and not _system_available_tool(item)
        )

    def _by_id(self) -> dict[str, ActiveCapability]:
        return {item.revision.capability_id: item for item in self._eligible()}

    def _mcp_by_id(self) -> dict[str, MCPGatewayServer]:
        return {
            f"mcp-server://{item.server_id}": item
            for item in self._mcp_gateway.servers()
        }

    def _resolve_mcp_server(self, name: str) -> MCPGatewayServer:
        return self._mcp_gateway.resolve_server(_required_text(name, "server_name"))

    @staticmethod
    def _summary(item: ActiveCapability) -> dict[str, object]:
        revision = item.revision
        return {
            "name": revision.content.display_name,
            "kind": revision.kind,
            "description": revision.content.description,
            "keywords": list(item.index_revision.document.keywords),
        }

    @staticmethod
    def _mcp_summary(server: MCPGatewayServer) -> dict[str, object]:
        return {
            "name": str(server.raw_config.get("display_name") or server.server_id),
            "kind": "mcp_server",
            "description": str(server.raw_config.get("description") or ""),
            "keywords": list(dict.fromkeys(
                value
                for value in (
                    str(server.catalog.server_name or "").strip(),
                    str(server.catalog.server_title or "").strip(),
                    *(str(item or "").strip() for item in server.catalog.capabilities),
                )
                if value
            )),
        }

    @staticmethod
    def _mcp_entry_summary(
        server: MCPGatewayServer,
        entry: MCPGatewayCatalogEntry,
    ) -> dict[str, object]:
        return {
            "name": entry.display_name,
            "kind": entry.kind,
            "description": entry.description,
            "keywords": list(entry.keywords),
            "server_name": str(server.raw_config.get("display_name") or server.server_id),
        }

    @staticmethod
    def _active_description(item: ActiveCapability) -> dict[str, object]:
        revision = item.revision
        summary = CapabilityCatalogRuntime._summary(item)
        if revision.kind == "tool":
            definition = ToolDefinition.model_validate(revision.content.definition)
            return {
                **summary,
                "definition": {
                    "input_schema": definition.input_schema,
                    "context_schema": definition.context_schema,
                    "output_schema": definition.output_schema,
                    "risk_level": definition.runtime_policy.risk_level,
                    "approval": definition.runtime_policy.approval,
                    "effects": list(definition.effects),
                    "read_only": definition.read_only,
                    "concurrent": definition.runtime_policy.allow_parallel_calls,
                    "max_parallel_calls": definition.runtime_policy.max_parallel_calls,
                    "timeout_seconds": definition.runtime_policy.timeout_seconds,
                },
            }
        if revision.kind == "skill":
            definition = SkillDefinition.model_validate(revision.content.definition)
            return {
                **summary,
                "definition": {
                    "skill_name": definition.name,
                    "contents": [item.logical_path for item in definition.contents],
                    "load_with": "skill",
                },
            }
        return summary


def _delegatable(item: ActiveCapability) -> bool:
    return capability_is_delegatable(item.revision.capability_id)


def _system_available_tool(item: ActiveCapability) -> bool:
    if item.revision.kind != "tool":
        return False
    definition = ToolDefinition.model_validate(item.revision.content.definition)
    return definition.system_available


def _required_text(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text


def _matches_active_capability(item: ActiveCapability, requested: str) -> bool:
    revision = item.revision
    return requested.casefold() in {
        revision.capability_id.casefold(),
        revision.content.display_name.casefold(),
    }


def _matches_mcp_server(server: MCPGatewayServer, requested: str) -> bool:
    display_name = str(server.raw_config.get("display_name") or server.server_id).strip()
    return requested.casefold() in {server.server_id.casefold(), display_name.casefold()}


def _matches_public_name(entry: MCPGatewayCatalogEntry, requested: str) -> bool:
    return requested.casefold() in {
        entry.display_name.casefold(),
        entry.operation_name.casefold(),
    }


_Match = TypeVar("_Match")


def _require_unique_match(matches: tuple[_Match, ...], requested: str) -> _Match:
    if not matches:
        raise LookupError(f"capability not found: {requested}")
    if len(matches) > 1:
        raise LookupError(f"capability name is ambiguous: {requested}")
    return next(iter(matches))


def _digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()
