from __future__ import annotations

from typing import Any

from langgraph.config import get_stream_writer


def context_event_payload(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"event_type": event_type, **payload}


def emit_context_event(
    *,
    services: Any | None,
    state: Any | None,
    event_type: str,
    payload: dict[str, Any],
    node_id: str | None = None,
) -> None:
    event_payload = context_event_payload(event_type, payload)
    if services is not None and state is not None and getattr(services, "observability_manager", None) is not None:
        from agent_factory.runtime_kernel.observability.schema import TraceEvent

        event = TraceEvent(
            trace_id=state.observability.trace_id,
            run_id=state.run.run_id,
            event_type=event_type,
            node_id=node_id,
            payload=event_payload,
        )
        services.observability_manager.emit(event)
        state.observability.events.append(event.model_dump(mode="json"))
    _emit_stream_event(event_payload)


def _emit_stream_event(payload: dict[str, Any]) -> None:
    try:
        writer = get_stream_writer()
    except Exception:
        return
    try:
        writer({"type": "context_event", "payload": payload})
    except Exception:
        return
