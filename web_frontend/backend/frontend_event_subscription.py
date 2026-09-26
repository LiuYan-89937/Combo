from __future__ import annotations

import asyncio
from typing import Any


_TEXT_DELTA_EVENTS = frozenset({
    "message_part_delta", "model_reasoning_delta", "model_stream_delta",
})


def compact_frontend_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    previous_key: tuple[Any, ...] | None = None
    for event in events:
        key = _delta_key(event)
        if key is not None and key == previous_key:
            previous = compacted[-1]
            previous["payload"]["delta"] += event["payload"]["delta"]
            previous["timestamp"] = event.get("timestamp")
        else:
            compacted.append({**event, "payload": dict(event.get("payload") or {})})
        previous_key = key
    return compacted


def _delta_key(event: dict[str, Any]) -> tuple[Any, ...] | None:
    payload = event.get("payload") or {}
    if event.get("event_type") not in _TEXT_DELTA_EVENTS or not isinstance(payload.get("delta"), str):
        return None
    return (
        event.get("event_type"), event.get("run_id"), event.get("request_id"),
        event.get("node_id"), payload.get("stream_id"),
        payload.get("message_id"), payload.get("part_id"),
    )


class FrontendEventSubscription:
    """A bounded, event-loop-owned stream with an explicit terminal state."""

    def __init__(self, *, principal_id: str, capacity: int) -> None:
        self.principal_id = principal_id
        self.close_reason: str | None = None
        self._queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=capacity)

    def offer(self, event: dict[str, Any]) -> None:
        if self.close_reason is not None:
            return
        # Preserve each live event's identity across the snapshot boundary.
        # Recovery batches can coalesce text once their covered IDs are frozen.
        self._queue.put_nowait(event)

    async def receive(self) -> dict[str, Any] | None:
        return await self._queue.get()

    def close(self, reason: str) -> None:
        if self.close_reason is not None:
            return
        self.close_reason = reason
        while not self._queue.empty():
            self._queue.get_nowait()
        self._queue.put_nowait(None)
