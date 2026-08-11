from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.services import RuntimeServices
from agent_factory.runtime_kernel.observability.schema import RuntimeObservationEvent
from agent_factory.runtime_kernel.state import RuntimeState


def emit_state_event(
    services: RuntimeServices,
    state: RuntimeState,
    event_type: str,
    *,
    node_id: str | None = None,
    message: str | None = None,
    payload: dict[str, Any] | None = None,
    subgraph_id: str | None = None,
) -> None:
    event = RuntimeObservationEvent(
        trace_id=state.observability.trace_id,
        run_id=state.run.run_id,
        event_type=event_type,
        node_id=node_id,
        subgraph_id=subgraph_id,
        message=message,
        payload=payload or {},
    )
    services.observability_manager.emit(event)
    state.observability.events.append(event.model_dump(mode="json"))
    trace_recorder = getattr(services, "trace_recorder", None)
    if trace_recorder is not None:
        trace_recorder.record_event(
            trace_id=state.observability.trace_id,
            run_id=state.run.run_id,
            event_type=event_type,
            node_id=node_id,
            message=message,
            payload=payload or {},
        )


def apply_node_metrics(state: RuntimeState, duration_seconds: float) -> None:
    duration_ms = int(duration_seconds * 1000)
    metrics = dict(state.observability.metrics)
    metrics["turn_count"] = state.execution.turn_count
    metrics["total_latency_ms"] = int(metrics.get("total_latency_ms", 0)) + duration_ms
    metrics["max_node_latency_ms"] = max(int(metrics.get("max_node_latency_ms", 0)), duration_ms)
    state.observability.metrics = metrics
