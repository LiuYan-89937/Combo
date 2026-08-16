from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json

from combo.dynamic_runtime.capability_resolution_store import CapabilityResolutionReceiptStore
from combo.dynamic_runtime.capability_resolver import CapabilitySearchIndex
from combo.dynamic_runtime.capability_store import ActiveCapability, CapabilityStore
from combo.dynamic_runtime.delegation_policy import capability_is_delegatable
from combo.dynamic_runtime.mcp_gateway import MCPGateway, MCPGatewayTool
from combo.runtime_protocol import CapabilityTrustLevel


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
            *(self._mcp_summary(tool) for tool in self._mcp_gateway.tools()),
        ]

    def search(self, query: str, *, limit: int) -> list[dict[str, object]]:
        normalized = str(query or "").strip()
        if not normalized:
            raise ValueError("capability search query must not be empty")
        if limit < 1:
            raise ValueError("capability search limit must be positive")
        eligible = self._eligible()
        by_id = {item.revision.capability_id: item for item in eligible}
        matches = self._search_index.search(requirements=(normalized,), candidates=eligible)
        published_results = [
            {
                **self._summary(by_id[match.capability_id]),
                "score": match.score,
                "search_evidence_id": match.evidence_id,
            }
            for match in matches[:limit]
            if match.capability_id in by_id
        ]
        external_results = [
            {
                **self._mcp_summary(tool),
                "score": score,
                "search_evidence_id": f"mcp-gateway:{tool.content_digest}",
            }
            for tool in self._mcp_gateway.tools()
            if (score := _mcp_match_score(normalized, tool)) > 0
        ]
        return sorted(
            (*published_results, *external_results),
            key=lambda item: (-float(item["score"]), str(item["name"])),
        )[:limit]

    def inspect(self, capability_id: str) -> dict[str, object]:
        requested = _required_text(capability_id, "capability_id")
        external = self._mcp_by_id().get(requested)
        if external is not None:
            return {
                **self._mcp_summary(external),
                "source_uri": f"mcp-gateway://{external.server_id}/tools/{external.definition.upstream_tool_name}",
                "resolved_version": external.definition.server_content_digest,
                "dependencies": [],
                "resources": [],
                "definition_schema": "mcp_tool_definition.v3",
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
        selected_external: dict[str, MCPGatewayTool] = {}
        visiting: list[str] = []

        def include(capability_id: str) -> None:
            external_tool = external.get(capability_id)
            if external_tool is not None:
                selected_external[capability_id] = external_tool
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
            if health.valid_until is not None and datetime.fromisoformat(health.valid_until) <= datetime.now(UTC):
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
                "capability_id": tool.capability_id,
                "kind": "mcp_tool",
                "revision": tool.server_revision,
                "resolved_version": tool.definition.server_content_digest,
                "content_digest": tool.content_digest,
            }
            for tool in sorted(selected_external.values(), key=lambda value: value.capability_id)
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
        )

    def _by_id(self) -> dict[str, ActiveCapability]:
        return {item.revision.capability_id: item for item in self._eligible()}

    def _mcp_by_id(self) -> dict[str, MCPGatewayTool]:
        return {item.capability_id: item for item in self._mcp_gateway.tools()}

    @staticmethod
    def _summary(item: ActiveCapability) -> dict[str, object]:
        revision = item.revision
        return {
            "name": revision.content.display_name,
            "kind": revision.kind,
            "description": revision.content.description,
        }

    @staticmethod
    def _mcp_summary(tool: MCPGatewayTool) -> dict[str, object]:
        return {
            "name": tool.display_name,
            "kind": "mcp_tool",
            "description": tool.description,
        }


def _normalize(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _mcp_match_score(query: str, tool: MCPGatewayTool) -> float:
    needle = _normalize(query)
    fields = (
        _normalize(tool.display_name),
        _normalize(tool.description),
        _normalize(tool.definition.upstream_tool_name),
        _normalize(tool.definition.model_alias),
    )
    if needle in {fields[0], fields[2], fields[3]}:
        return 1.0
    if any(needle in field for field in fields):
        return 0.75
    tokens = set(needle.split())
    haystack = set(" ".join(fields).split())
    return len(tokens & haystack) / len(tokens) * 0.5 if tokens else 0.0


def _delegatable(item: ActiveCapability) -> bool:
    return capability_is_delegatable(item.revision.capability_id)


def _required_text(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text


def _digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()
