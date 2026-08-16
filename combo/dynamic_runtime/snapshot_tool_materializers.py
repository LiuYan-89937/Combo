from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from langchain_core.tools import BaseTool

from combo.dynamic_runtime.capability_definitions import (
    MCPToolDefinition,
    ToolDefinition,
)
from combo.dynamic_runtime.snapshot_tool_registry import (
    MaterializedSnapshotTool,
    ReleaseCallback,
)
from combo.runtime_protocol import (
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
        definition = _runtime_visible_tool_definition(definition, runtime_instance)
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
        if projection.kind != self.kind or projection.runtime_definition_schema != "mcp_tool_definition.v3":
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


def _runtime_visible_tool_definition(
    definition: ToolDefinition,
    runtime_instance: RuntimeInstance,
) -> ToolDefinition:
    if definition.model_alias != "memory" or runtime_instance.request.policy_snapshot.memory_agent_write_enabled:
        return definition
    schema = dict(definition.input_schema)
    branches = schema.get("oneOf")
    if not isinstance(branches, list):
        raise ValueError("memory tool input schema must declare oneOf actions")
    visible = [branch for branch in branches if _schema_action(branch) != "write"]
    if len(visible) == len(branches):
        raise ValueError("memory tool input schema does not expose a write action")
    return definition.model_copy(
        update={
            "model_description": (
                "Search or list the current principal's user/workspace memories, or delete an existing memory. "
                "Proactive memory writes are disabled for this runtime turn."
            ),
            "input_schema": {**schema, "oneOf": visible},
        }
    )


def _schema_action(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    properties = value.get("properties")
    if not isinstance(properties, dict):
        return ""
    action = properties.get("action")
    return str(action.get("const") or "") if isinstance(action, dict) else ""
