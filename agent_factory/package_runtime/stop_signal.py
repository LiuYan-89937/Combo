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
