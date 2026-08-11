from __future__ import annotations

import asyncio
from dataclasses import dataclass

from agent_factory.runtime_protocol import OutboxRecord, RuntimeEvent


@dataclass(frozen=True, slots=True)
class RuntimeEventStreamConfig:
    subscriber_queue_capacity: int

    def __post_init__(self) -> None:
        if self.subscriber_queue_capacity < 1:
            raise ValueError("subscriber_queue_capacity must be positive")


class RuntimeEventSubscription:
    def __init__(self, *, session_id: str, queue_capacity: int) -> None:
        self.session_id = _required_text(session_id, "session_id")
        self.queue: asyncio.Queue[RuntimeEvent] = asyncio.Queue(maxsize=queue_capacity)
        self.disconnected = asyncio.Event()
        self.disconnect_reason: str | None = None

    def disconnect(self, reason: str) -> None:
        if self.disconnected.is_set():
            return
        self.disconnect_reason = _required_text(reason, "disconnect reason")
        self.disconnected.set()


class RuntimeEventBroadcaster:
    """Best-effort live projection; RuntimeEventStore remains the replay authority."""

    def __init__(self, config: RuntimeEventStreamConfig) -> None:
        self._config = config
        self._subscriptions: set[RuntimeEventSubscription] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self, session_id: str) -> RuntimeEventSubscription:
        subscription = RuntimeEventSubscription(
            session_id=session_id,
            queue_capacity=self._config.subscriber_queue_capacity,
        )
        async with self._lock:
            self._subscriptions.add(subscription)
        return subscription

    async def unsubscribe(self, subscription: RuntimeEventSubscription) -> None:
        async with self._lock:
            self._subscriptions.discard(subscription)
        subscription.disconnect("client_unsubscribed")

    async def publish(self, record: OutboxRecord) -> None:
        if record.aggregate_kind != "runtime_instance":
            return
        event = RuntimeEvent.model_validate(record.payload)
        async with self._lock:
            subscribers = tuple(self._subscriptions)
        overflowed: list[RuntimeEventSubscription] = []
        for subscription in subscribers:
            if subscription.session_id != event.session_id or subscription.disconnected.is_set():
                continue
            try:
                subscription.queue.put_nowait(event)
            except asyncio.QueueFull:
                subscription.disconnect("slow_consumer")
                overflowed.append(subscription)
        if overflowed:
            async with self._lock:
                for subscription in overflowed:
                    self._subscriptions.discard(subscription)


def _required_text(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text
