from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.config import get_stream_writer

from agent_factory.runtime_kernel.observability.schema import RuntimeObservationEvent


ModelEventSink = Callable[[dict[str, Any]], None]


def emit_runtime_node_event(event: RuntimeObservationEvent) -> None:
    _emit_node_event_payload(event.model_dump(mode="json"))


def langgraph_model_event_sink(node_id: str) -> ModelEventSink:
    """Bridge ModelOperationService events into the active LangGraph custom stream."""

    normalized_node_id = str(node_id).strip()
    if not normalized_node_id:
        raise ValueError("node_id is required for streamed model events")

    def emit(payload: dict[str, Any]) -> None:
        event_type = str(payload.get("event_type") or "").strip()
        if not event_type:
            return
        _emit_node_event_payload(
            {
                "event_type": event_type,
                "node_id": normalized_node_id,
                "payload": {
                    key: value
                    for key, value in payload.items()
                    if key != "event_type"
                },
            }
        )

    return emit


def _emit_node_event_payload(payload: dict[str, Any]) -> None:
    try:
        writer = get_stream_writer()
    except Exception:
        return
    try:
        writer({"type": "node_event", "payload": payload})
    except Exception:
        return
