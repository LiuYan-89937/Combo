from __future__ import annotations

from dataclasses import dataclass, field
import threading
from typing import Any

from agent_factory.factory_graph.frontend_bridge.event_normalizer import VisibleAssistantMessage


@dataclass(slots=True)
class RuntimeStopSignal:
    event: threading.Event = field(default_factory=threading.Event)
    reason: str = "user_cancelled"
    visible_output: VisibleAssistantMessage | None = None

    def request(self, *, reason: str, visible_output: Any = None) -> None:
        self.reason = reason
        self.visible_output = _visible_output_message(visible_output)
        self.event.set()

    def is_set(self) -> bool:
        return self.event.is_set()

    def resolved_visible_output(self, fallback: VisibleAssistantMessage) -> VisibleAssistantMessage:
        if self.visible_output is None:
            return fallback
        return self.visible_output


class RuntimeStopRegistry:
    """Thread-safe ownership of cancellation signals for active runtime requests."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._signals: dict[str, RuntimeStopSignal] = {}

    def register(self, request_id: str) -> RuntimeStopSignal:
        signal = RuntimeStopSignal()
        with self._lock:
            self._signals[request_id] = signal
        return signal

    def request(
        self,
        *,
        reason: str,
        request_id: str | None = None,
        visible_output: Any = None,
    ) -> int:
        target = (request_id or "").strip()
        with self._lock:
            if target:
                request_ids = [target] if target in self._signals else []
            else:
                request_ids = list(self._signals)
            for active_request_id in request_ids:
                self._signals[active_request_id].request(
                    reason=reason,
                    visible_output=visible_output,
                )
            return len(request_ids)

    def release(self, request_id: str, signal: RuntimeStopSignal) -> None:
        with self._lock:
            if self._signals.get(request_id) is signal:
                self._signals.pop(request_id, None)


def _visible_output_message(value: Any) -> VisibleAssistantMessage | None:
    if not isinstance(value, dict):
        return None
    content = _optional_text(value.get("content"))
    reasoning_content = _optional_text(value.get("reasoning_content"))
    if not content and not reasoning_content:
        return None
    return VisibleAssistantMessage(
        content=content,
        reasoning_content=reasoning_content,
        stream_id=_optional_text(value.get("stream_id")),
        node_id=_optional_text(value.get("node_id")),
    )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
