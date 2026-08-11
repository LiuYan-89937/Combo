from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_factory.runtime_kernel.fixed_graphs import CompiledRuntimeGraph, build_fixed_runtime_graph
from agent_factory.runtime_kernel.model_operations import ModelOperationService, RuntimeModelHandleRegistry
from agent_factory.runtime_kernel.observability.emitter import ObservabilityManager
from agent_factory.runtime_kernel.services import RuntimeServices
from agent_factory.dynamic_runtime.snapshot_tool_registry import (
    RuntimeScopedToolRegistry,
    SnapshotToolRegistryFactory,
)


@dataclass(frozen=True, slots=True)
class DynamicRuntimeServiceSet:
    services: RuntimeServices
    model_handles: RuntimeModelHandleRegistry
    scoped_tool_registry: RuntimeScopedToolRegistry
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
        memory_store: Any,
        context_system: Any,
        context_engine: Any,
        memory_system: Any | None = None,
        knowledge_runtime: Any | None = None,
        artifact_store: Any | None = None,
        scheduler_store: Any | None = None,
        scheduler_runtime: Any | None = None,
        trace_recorder: Any | None = None,
        trace_reader: Any | None = None,
        runtime_resources: dict[str, Any] | None = None,
        tool_runtime_resources: dict[str, Any] | None = None,
    ) -> None:
        self._snapshot_tool_registries = _required_dependency(
            snapshot_tool_registries,
            "snapshot_tool_registries",
        )
        self._checkpointer = _required_dependency(checkpointer, "checkpointer")
        self._memory_store = _required_dependency(memory_store, "memory_store")
        self._context_system = _required_dependency(context_system, "context_system")
        self._context_engine = _required_dependency(context_engine, "context_engine")
        self._memory_system = memory_system
        self._knowledge_runtime = knowledge_runtime
        self._artifact_store = artifact_store
        self._scheduler_store = scheduler_store
        self._scheduler_runtime = scheduler_runtime
        self._trace_recorder = trace_recorder
        self._trace_reader = trace_reader
        self._runtime_resources = dict(runtime_resources or {})
        self._tool_runtime_resources = dict(tool_runtime_resources or {})

    def build(self) -> DynamicRuntimeServiceSet:
        model_handles = RuntimeModelHandleRegistry()
        scoped_tool_registry = RuntimeScopedToolRegistry()
        services = RuntimeServices(
            model_operation_service=ModelOperationService(model_handles),
            tool_registry=scoped_tool_registry,
            memory_store=self._memory_store,
            memory_system=self._memory_system,
            knowledge_runtime=self._knowledge_runtime,
            context_system=self._context_system,
            context_engine=self._context_engine,
            observability_manager=ObservabilityManager(),
            checkpointer=self._checkpointer,
            scheduler_store=self._scheduler_store,
            scheduler_runtime=self._scheduler_runtime,
            artifact_store=self._artifact_store,
            trace_recorder=self._trace_recorder,
            trace_reader=self._trace_reader,
            runtime_resources=self._runtime_resources,
            tool_runtime_resources=self._tool_runtime_resources,
        )
        services.validate_required(
            [
                "model_operation_service",
                "tool_registry",
                "memory_store",
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
            snapshot_tool_registries=self._snapshot_tool_registries,
            react_graph=react_graph,
            plan_and_execute_graph=plan_graph,
        )


def _required_dependency(value: Any, name: str) -> Any:
    if value is None:
        raise ValueError(f"dynamic runtime services require {name}")
    return value
