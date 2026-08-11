from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.observability.schema import RuntimeObservationEvent


class ObservabilityManager:
    """In-process projection of observations emitted by a fixed runtime graph."""

    def __init__(self) -> None:
        self.events: list[RuntimeObservationEvent] = []

    def emit(self, event: RuntimeObservationEvent) -> None:
        self.events.append(event)

    def emit_dict(self, data: dict[str, Any]) -> None:
        self.emit(RuntimeObservationEvent.model_validate(data))

    def list_events(self) -> list[RuntimeObservationEvent]:
        return list(self.events)
