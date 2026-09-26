from __future__ import annotations

from typing import Any

from combo.dynamic_runtime.model_service import RuntimeModelResolver
from combo.dynamic_runtime.repositories import RuntimeInstanceStore
from combo.dynamic_runtime.runtime_results import (
    interrupt_payloads,
    latest_context_window,
    recompute_context_window_ratios,
)
from combo.dynamic_runtime.services import DynamicRuntimeServiceSet
from combo.runtime_kernel.state import RuntimeState
from combo.runtime_protocol import RuntimeInstance


class RuntimeInspectionService:
    """Read current runtime projections from the authoritative graph checkpoint."""

    def __init__(
        self,
        *,
        service_set: DynamicRuntimeServiceSet,
        runtime_instances: RuntimeInstanceStore,
        model_resolver: RuntimeModelResolver,
    ) -> None:
        self._service_set = service_set
        self._runtime_instances = runtime_instances
        self._model_resolver = model_resolver

    def pending_interrupts(self, runtime_instance_id: str) -> tuple[dict[str, Any], ...]:
        instance = self._runtime_instances.get(runtime_instance_id)
        if instance.status not in {"waiting_approval", "waiting_external"}:
            raise RuntimeError("runtime instance is not waiting for an interrupt response")
        return tuple(interrupt_payloads(raw={}, checkpoint=self._checkpoint(instance)))

    def current_observations(self, runtime_instance_id: str) -> list[dict[str, Any]]:
        return [
            event.model_dump(mode="json")
            for event in self._service_set.services.observability_manager.list_events()
            if event.run_id == runtime_instance_id
        ]

    def current_plan(self, runtime_instance_id: str) -> dict[str, Any] | None:
        instance = self._runtime_instances.get(runtime_instance_id)
        if instance.request.strategy != "plan_and_execute":
            return None
        values = self._checkpoint_values(instance)
        raw_runtime = values.get("runtime")
        if not isinstance(raw_runtime, dict):
            return None
        state = RuntimeState.model_validate(raw_runtime)
        if state.plan.status == "empty":
            return None
        return state.plan.model_dump(mode="json")

    def current_context_window(self, runtime_instance_id: str) -> dict[str, Any] | None:
        instance = self._runtime_instances.get(runtime_instance_id)
        values = self._checkpoint_values(instance)
        raw_runtime = values.get("runtime")
        if not isinstance(raw_runtime, dict):
            return None
        context_window = latest_context_window(
            RuntimeState.model_validate(raw_runtime),
            graph_messages=list(values.get("messages") or []),
        )
        if context_window is None:
            return None
        limits = self._model_resolver.context_limits_for_snapshot(
            instance.request.policy_snapshot.model
        )
        current_limits = {key: value for key, value in limits.items() if value is not None}
        return recompute_context_window_ratios(
            {
                **{key: value for key, value in context_window.items() if value is not None},
                **current_limits,
            }
        )

    def _checkpoint(self, instance: RuntimeInstance) -> Any:
        graph = self._service_set.graph_for(instance.request.strategy)
        return graph.graph_app.get_state(
            {"configurable": {"thread_id": instance.runtime_instance_id}}
        )

    def _checkpoint_values(self, instance: RuntimeInstance) -> dict[str, Any]:
        values = getattr(self._checkpoint(instance), "values", None)
        if values is None:
            return {}
        if not isinstance(values, dict):
            raise TypeError("runtime checkpoint values must be an object")
        return values
