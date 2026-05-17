from __future__ import annotations

from langgraph.config import get_stream_writer

from agent_factory.runtime_kernel.bindings import RuntimeServices
from agent_factory.runtime_kernel.observability.schema import TraceEvent
from agent_factory.runtime_kernel.state import RuntimeState
from agent_factory.runtime_render import RuntimeRenderEvent


def runtime_render_event_to_trace_event(
    render_event: RuntimeRenderEvent,
    *,
    trace_id: str,
    run_id: str,
) -> TraceEvent:
    payload = {
        "runtime_render": render_event.model_dump(mode="json"),
    }
    return TraceEvent(
        trace_id=trace_id,
        run_id=run_id,
        event_type=render_event.event_type,
        node_id=render_event.node_id,
        message=render_event.message,
        payload=payload,
    )


def trace_event_to_runtime_render_event(trace_event: TraceEvent) -> RuntimeRenderEvent | None:
    raw_event = trace_event.payload.get("runtime_render")
    if not isinstance(raw_event, dict):
        return None
    return RuntimeRenderEvent.model_validate(raw_event)


def emit_runtime_render_event(
    *,
    services: RuntimeServices,
    state: RuntimeState,
    render_event: RuntimeRenderEvent,
) -> None:
    trace_event = runtime_render_event_to_trace_event(
        render_event,
        trace_id=state.observability.trace_id,
        run_id=state.run.run_id,
    )
    services.observability_manager.emit(trace_event)
    state.observability.events.append(trace_event.model_dump(mode="json"))
    _emit_stream_event(render_event)


def _emit_stream_event(render_event: RuntimeRenderEvent) -> None:
    try:
        writer = get_stream_writer()
    except Exception:
        return
    try:
        writer(
            {
                "type": "runtime_render_event",
                "payload": render_event.model_dump(mode="json"),
            }
        )
    except Exception:
        return
