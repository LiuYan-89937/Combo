from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from langchain_core.tools import BaseTool

from agent_factory.dynamic_runtime.capability_definitions import (
    MCPToolDefinition,
    ToolDefinition,
)
from agent_factory.dynamic_runtime.snapshot_tool_registry import (
    MaterializedSnapshotTool,
    ReleaseCallback,
)
from agent_factory.runtime_protocol import (
    CapabilityProjectionSnapshot,
    CapabilitySnapshot,
    RuntimeInstance,
)


@dataclass(frozen=True, slots=True)
class MaterializedToolRuntime:
    tool: BaseTool
    release_callback: ReleaseCallback

    def __post_init__(self) -> None:
        if not callable(self.release_callback):
            raise TypeError("materialized tool runtime requires a release callback")


class ToolCapabilityRuntimeAdapter(Protocol):
    def materialize(
        self,
        *,
        definition: ToolDefinition,
        projection: CapabilityProjectionSnapshot,
        capability_snapshot: CapabilitySnapshot,
        runtime_instance: RuntimeInstance,
    ) -> MaterializedToolRuntime:
        ...


class MCPToolCapabilityRuntimeAdapter(Protocol):
    def materialize(
        self,
        *,
        definition: MCPToolDefinition,
        projection: CapabilityProjectionSnapshot,
        capability_snapshot: CapabilitySnapshot,
        runtime_instance: RuntimeInstance,
    ) -> MaterializedToolRuntime:
        ...


class ToolProjectionMaterializer:
    kind = "tool"

    def __init__(self, adapter: ToolCapabilityRuntimeAdapter) -> None:
        self._adapter = adapter

    def materialize(
        self,
        *,
        projection: CapabilityProjectionSnapshot,
        capability_snapshot: CapabilitySnapshot,
        runtime_instance: RuntimeInstance,
    ) -> tuple[MaterializedSnapshotTool, ...]:
        if projection.kind != self.kind or projection.runtime_definition_schema != "tool_definition.v2":
            raise ValueError("tool materializer received a non-tool projection")
        definition = ToolDefinition.model_validate(projection.runtime_definition)
        _require_single_alias(projection, definition.model_alias)
        runtime = self._adapter.materialize(
            definition=definition,
            projection=projection,
            capability_snapshot=capability_snapshot,
            runtime_instance=runtime_instance,
        )
        return (
            MaterializedSnapshotTool(
                model_alias=definition.model_alias,
                capability_id=projection.capability_id,
                kind="tool",
                revision=projection.revision,
                content_digest=projection.content_digest,
                tool=runtime.tool,
                runtime_policy=definition.runtime_policy,
                release_callback=runtime.release_callback,
                system_available=definition.system_available,
            ),
        )


class MCPToolProjectionMaterializer:
    kind = "mcp_tool"

    def __init__(self, adapter: MCPToolCapabilityRuntimeAdapter) -> None:
        self._adapter = adapter

    def materialize(
        self,
        *,
        projection: CapabilityProjectionSnapshot,
        capability_snapshot: CapabilitySnapshot,
        runtime_instance: RuntimeInstance,
    ) -> tuple[MaterializedSnapshotTool, ...]:
        if projection.kind != self.kind or projection.runtime_definition_schema != "mcp_tool_definition.v2":
            raise ValueError("MCP tool materializer received a non-MCP-tool projection")
        definition = MCPToolDefinition.model_validate(projection.runtime_definition)
        _require_single_alias(projection, definition.model_alias)
        runtime = self._adapter.materialize(
            definition=definition,
            projection=projection,
            capability_snapshot=capability_snapshot,
            runtime_instance=runtime_instance,
        )
        return (
            MaterializedSnapshotTool(
                model_alias=definition.model_alias,
                capability_id=projection.capability_id,
                kind="mcp_tool",
                revision=projection.revision,
                content_digest=projection.content_digest,
                tool=runtime.tool,
                runtime_policy=definition.runtime_policy,
                release_callback=runtime.release_callback,
            ),
        )


def _require_single_alias(projection: CapabilityProjectionSnapshot, expected_alias: str) -> None:
    if projection.model_tool_ids != (expected_alias,):
        raise ValueError("tool projection alias differs from its immutable runtime definition")
