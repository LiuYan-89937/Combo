from __future__ import annotations

from dataclasses import dataclass
from threading import BoundedSemaphore, RLock
from typing import Any

from combo.dynamic_runtime.capability_catalog_runtime import CapabilityCatalogRuntime
from combo.dynamic_runtime.capability_resolver import MainTurnCapabilityResolver
from combo.dynamic_runtime.mcp_gateway import MCPGateway
from combo.dynamic_runtime.model_service import ResolvedRuntimePolicy, RuntimeModelResolver
from combo.dynamic_runtime.repositories import RuntimeInstanceStore
from combo.dynamic_runtime.snapshot_tool_registry import SnapshotToolRegistryFactory
from combo.runtime_protocol import CapabilitySnapshot, RuntimeInstance
from combo.tooling.execution_context import current_tool_call, tool_call_context


@dataclass(frozen=True, slots=True)
class BoundCapabilityInvocationRuntime:
    coordinator: "CapabilityInvocationRuntime"
    runtime_instance: RuntimeInstance

    def invoke(
        self,
        *,
        name: str,
        kind: str,
        server_name: str | None,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        return self.coordinator.invoke(
            runtime_instance=self.runtime_instance,
            name=name,
            kind=kind,
            server_name=server_name,
            arguments=arguments,
        )


class CapabilityInvocationRuntime:
    """Resolve one searched Tool and execute it through its native policy chain."""

    def __init__(
        self,
        *,
        catalog: CapabilityCatalogRuntime,
        mcp_gateway: MCPGateway,
        runtime_instances: RuntimeInstanceStore,
    ) -> None:
        self._catalog = catalog
        self._mcp_gateway = mcp_gateway
        self._runtime_instances = runtime_instances
        self._capability_resolver: MainTurnCapabilityResolver | None = None
        self._model_resolver: RuntimeModelResolver | None = None
        self._registry_factory: SnapshotToolRegistryFactory | None = None
        self._concurrency_lock = RLock()
        self._concurrency: dict[tuple[str, str], BoundedSemaphore] = {}

    def bind_execution(
        self,
        *,
        capability_resolver: MainTurnCapabilityResolver,
        model_resolver: RuntimeModelResolver,
        registry_factory: SnapshotToolRegistryFactory,
    ) -> None:
        with self._concurrency_lock:
            if self._capability_resolver is not None:
                raise RuntimeError("capability invocation runtime is already bound")
            self._capability_resolver = capability_resolver
            self._model_resolver = model_resolver
            self._registry_factory = registry_factory

    def for_runtime(self, instance: RuntimeInstance) -> BoundCapabilityInvocationRuntime:
        return BoundCapabilityInvocationRuntime(self, instance)

    def invoke(
        self,
        *,
        runtime_instance: RuntimeInstance,
        name: str,
        kind: str,
        server_name: str | None,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        target = self._catalog.resolve_invocation_target(
            name=name,
            kind=kind,
            server_name=server_name,
        )
        snapshot = self._target_snapshot(runtime_instance, target.capability_id, target.kind)
        self._runtime_instances.retain_capability_snapshot(snapshot)
        request = runtime_instance.request.model_copy(
            update={"capability_snapshot_id": snapshot.snapshot_id}
        )
        target_instance = runtime_instance.model_copy(
            update={
                "request": request,
                "capability_snapshot_id": snapshot.snapshot_id,
            }
        )
        registry_factory = self._required_registry_factory()
        lease = registry_factory.materialize(
            capability_snapshot=snapshot,
            runtime_instance=target_instance,
        )
        try:
            tool = lease.registry.tool_for_capability(target.capability_id)
            combo_metadata = _combo_metadata(tool)
            semaphore = self._target_semaphore(
                capability_id=target.capability_id,
                content_digest=str(combo_metadata.get("capability_content_digest") or ""),
                maximum=int(combo_metadata.get("max_parallel_calls") or 1),
            )
            current = current_tool_call()
            tool_call_id = current.tool_call_id if current is not None else target.capability_id
            origin_node_id = current.origin_node_id if current is not None else ""
            origin_impl = current.origin_impl if current is not None else ""
            event_sink = current.event_sink if current is not None else None
            with semaphore, tool_call_context(
                tool_id=tool.name,
                tool_call_id=tool_call_id,
                origin_node_id=origin_node_id,
                origin_impl=origin_impl,
                event_sink=event_sink,
            ):
                result = tool.invoke(arguments)
            if not isinstance(result, dict):
                raise RuntimeError("invoked capability returned a non-object observation")
            return {
                **result,
                "tool_id": target.public_name,
            }
        finally:
            lease.release()

    def _target_snapshot(
        self,
        runtime_instance: RuntimeInstance,
        capability_id: str,
        kind: str,
    ) -> CapabilitySnapshot:
        if kind == "mcp_tool":
            return self._mcp_gateway.augment_snapshot_tools(
                CapabilitySnapshot(
                    selections=(),
                    projections=(),
                    tool_ids=(),
                    tool_aliases=(),
                ),
                capability_ids=(capability_id,),
            )
        policy_snapshot = runtime_instance.request.policy_snapshot
        model_snapshot = policy_snapshot.model
        model_resolver, capability_resolver = self._required_resolution()
        resolved_model = model_resolver.resolve_chat_model(
            operation=model_snapshot.operation,
            profile_id=model_snapshot.profile_id,
            expected_profile_revision=model_snapshot.profile_revision,
            expected_credential_revision=model_snapshot.credential_revision,
            reasoning_intensity=policy_snapshot.reasoning_intensity,
        )
        return capability_resolver.resolve_requirements(
            principal_id=runtime_instance.request.principal_id,
            requirements=(),
            policy=ResolvedRuntimePolicy(
                snapshot=policy_snapshot,
                chat_model=resolved_model,
            ),
            workspace_id=runtime_instance.request.workspace_id,
            include_system_capabilities=False,
            required_capability_ids=(capability_id,),
        )

    def _target_semaphore(
        self,
        *,
        capability_id: str,
        content_digest: str,
        maximum: int,
    ) -> BoundedSemaphore:
        if maximum < 1:
            raise ValueError("target Tool max_parallel_calls must be positive")
        key = (capability_id, content_digest)
        with self._concurrency_lock:
            semaphore = self._concurrency.get(key)
            if semaphore is None:
                semaphore = BoundedSemaphore(maximum)
                self._concurrency[key] = semaphore
            return semaphore

    def _required_registry_factory(self) -> SnapshotToolRegistryFactory:
        registry_factory = self._registry_factory
        if registry_factory is None:
            raise RuntimeError("capability invocation runtime is not bound")
        return registry_factory

    def _required_resolution(self) -> tuple[RuntimeModelResolver, MainTurnCapabilityResolver]:
        model_resolver = self._model_resolver
        capability_resolver = self._capability_resolver
        if model_resolver is None or capability_resolver is None:
            raise RuntimeError("capability invocation runtime is not bound")
        return model_resolver, capability_resolver


def _combo_metadata(tool: Any) -> dict[str, Any]:
    metadata = getattr(tool, "metadata", None)
    if not isinstance(metadata, dict):
        return {}
    combo = metadata.get("combo")
    return dict(combo) if isinstance(combo, dict) else {}
