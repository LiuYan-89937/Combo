from __future__ import annotations

from threading import RLock
from typing import Any

from combo.runtime_kernel.observability.schema import RuntimeObservationEvent


class ObservabilityManager:
    """In-process projection of observations emitted by a fixed runtime graph."""

    def __init__(self) -> None:
        self.events: list[RuntimeObservationEvent] = []
        self._lock = RLock()

    def emit(self, event: RuntimeObservationEvent) -> None:
        with self._lock:
            self.events.append(event)

    def emit_dict(self, data: dict[str, Any]) -> None:
        self.emit(RuntimeObservationEvent.model_validate(data))

    def list_events(self) -> list[RuntimeObservationEvent]:
        with self._lock:
            return list(self.events)

    def drain_durable_events(self, *, trace_id: str, run_id: str) -> list[RuntimeObservationEvent]:
        """Consume one execution's observations while retaining no transient stream fragments."""

        matched: list[RuntimeObservationEvent] = []
        retained: list[RuntimeObservationEvent] = []
        with self._lock:
            for event in self.events:
                if event.trace_id == trace_id and event.run_id == run_id:
                    if event.persistence == "durable":
                        matched.append(event)
                else:
                    retained.append(event)
            self.events = retained
        return matched
