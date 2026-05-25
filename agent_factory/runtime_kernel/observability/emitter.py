from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.observability.schema import RuntimeObservationEvent


SECRET_KEY_PARTS = (
    "api_key",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)


class ObservabilityManager:
    """In-process runtime observation buffer.

    The manager no longer owns trace spans or trace summaries. Durable trace
    facts are written by trace_system.TraceRecorder.
    """

    def __init__(self) -> None:
        self.events: list[RuntimeObservationEvent] = []

    def emit(self, event: RuntimeObservationEvent) -> None:
        event.payload = _redact(event.payload)
        if event.message:
            event.message = _redact_text(event.message)
        self.events.append(event)

    def emit_dict(self, data: dict[str, Any]) -> None:
        self.emit(RuntimeObservationEvent.model_validate(data))

    def list_events(self) -> list[RuntimeObservationEvent]:
        return list(self.events)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(part in key_text for part in SECRET_KEY_PARTS):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _redact_text(value: str) -> str:
    text = value
    for marker in SECRET_KEY_PARTS:
        if marker in text.lower():
            return "[REDACTED]"
    return text
