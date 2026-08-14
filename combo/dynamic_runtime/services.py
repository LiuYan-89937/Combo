from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from combo.runtime_kernel.fixed_graphs import CompiledRuntimeGraph, build_fixed_runtime_graph
from combo.runtime_kernel.model_operations import ModelOperationService, RuntimeModelHandleRegistry
from combo.runtime_kernel.observability.emitter import ObservabilityManager
from combo.runtime_kernel.services import RuntimeServices
from combo.dynamic_runtime.snapshot_tool_registry import (
    RuntimeScopedToolRegistry,
    SnapshotToolRegistryFactory,
)
from combo.dynamic_runtime.runtime_identity import RuntimeScopedContextResources


@dataclass(frozen=True, slots=True)
class DynamicRuntimeServiceSet:
    services: RuntimeServices
    model_handles: RuntimeModelHandleRegistry
    scoped_tool_registry: RuntimeScopedToolRegistry
    scoped_context_resources: RuntimeScopedContextResources
    snapshot_tool_registries: SnapshotToolRegistryFactory
    react_graph: CompiledRuntimeGraph
    plan_and_execute_graph: CompiledRuntimeGraph

    def graph_for(self, strategy: str) -> CompiledRuntimeGraph:
        if strategy == "react":
            return self.react_graph
        if strategy == "plan_and_execute":
            return self.plan_and_execute_graph
        raise ValueError(f"unsupported runtime strategy: {strategy}")


class DynamicRuntimeServicesFactory:
    """Build the fixed runtime service graph from explicitly owned dependencies."""

    def __init__(
        self,
        *,
        snapshot_tool_registries: SnapshotToolRegistryFactory,
        checkpointer: Any,
        graph_store: Any,
        context_system: Any,
        context_engine: Any,
        artifact_store: Any | None = None,
        scheduler_store: Any | None = None,
        scheduler_runtime: Any | None = None,
    ) -> None:
        self._snapshot_tool_registries = _required_dependency(
            snapshot_tool_registries,
            "snapshot_tool_registries",
        )
        self._checkpointer = _required_dependency(checkpointer, "checkpointer")
        self._graph_store = _required_dependency(graph_store, "graph_store")
        self._context_system = _required_dependency(context_system, "context_system")
        self._context_engine = _required_dependency(context_engine, "context_engine")
        self._artifact_store = artifact_store
        self._scheduler_store = scheduler_store
        self._scheduler_runtime = scheduler_runtime

    def build(self) -> DynamicRuntimeServiceSet:
        model_handles = RuntimeModelHandleRegistry()
        scoped_tool_registry = RuntimeScopedToolRegistry()
        scoped_context_resources = RuntimeScopedContextResources()
        services = RuntimeServices(
            model_operation_service=ModelOperationService(model_handles),
            tool_registry=scoped_tool_registry,
            graph_store=self._graph_store,
            context_system=self._context_system,
            context_engine=self._context_engine,
            observability_manager=ObservabilityManager(),
            checkpointer=self._checkpointer,
            scheduler_store=self._scheduler_store,
            scheduler_runtime=self._scheduler_runtime,
            artifact_store=self._artifact_store,
            runtime_context_resources=scoped_context_resources,
        )
        services.validate_required(
            [
                "model_operation_service",
                "tool_registry",
                "graph_store",
                "context_system",
                "context_engine",
                "observability_manager",
                "checkpointer",
            ]
        )
        react_graph = build_fixed_runtime_graph("react", services=services)
        plan_graph = build_fixed_runtime_graph("plan_and_execute", services=services)
        return DynamicRuntimeServiceSet(
            services=services,
            model_handles=model_handles,
            scoped_tool_registry=scoped_tool_registry,
            scoped_context_resources=scoped_context_resources,
            snapshot_tool_registries=self._snapshot_tool_registries,
            react_graph=react_graph,
            plan_and_execute_graph=plan_graph,
        )


def _required_dependency(value: Any, name: str) -> Any:
    if value is None:
        raise ValueError(f"dynamic runtime services require {name}")
    return value
