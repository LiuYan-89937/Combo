from __future__ import annotations

import asyncio
from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable
from uuid import uuid4

from agent_factory.runtime_kernel.fixed_graphs import fixed_graph_model_output_visible
from agent_factory.runtime_protocol import CommandReceipt, OutboxRecord, RuntimeEvent, RuntimeInstance


@dataclass(eq=False, slots=True)
class FrontendEventSubscription:
    principal_id: str
    queue: asyncio.Queue[dict[str, Any]]


class FrontendEventBridge:
    """Projects the dynamic runtime onto the stable factory_frontend.v1 UI protocol."""

    def __init__(self, *, queue_capacity: int) -> None:
        if queue_capacity < 1:
            raise ValueError("frontend event queue capacity must be positive")
        self._queue_capacity = queue_capacity
        self.stream_id = uuid4().hex
        self._subscriptions: set[FrontendEventSubscription] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = RLock()
        self._frontend_request_id: Callable[[str, str], str] = lambda _runtime_id, request_id: request_id
        self._active_requests: Callable[[str], list[dict[str, Any]]] = lambda _principal_id: []
        self._delegated_task_name: Callable[[str], str | None] = lambda _task_id: None

    def bind_request_id_resolver(self, resolver: Callable[[str, str], str]) -> None:
        self._frontend_request_id = resolver

    def bind_active_request_resolver(
        self,
        resolver: Callable[[str], list[dict[str, Any]]],
    ) -> None:
        self._active_requests = resolver

    def bind_delegated_task_name_resolver(
        self,
        resolver: Callable[[str], str | None],
    ) -> None:
        self._delegated_task_name = resolver

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        with self._lock:
            self._loop = loop

    def stop(self) -> None:
        with self._lock:
            self._loop = None
            self._subscriptions.clear()

    async def subscribe(self, principal_id: str) -> FrontendEventSubscription:
        subscription = FrontendEventSubscription(
            principal_id=_required_text(principal_id, "principal_id"),
            queue=asyncio.Queue(maxsize=self._queue_capacity),
        )
        with self._lock:
            self._subscriptions.add(subscription)
        return subscription

    async def unsubscribe(self, subscription: FrontendEventSubscription) -> None:
        with self._lock:
            self._subscriptions.discard(subscription)

    async def publish_record(self, record: OutboxRecord, *, principal_id: str) -> None:
        if record.aggregate_kind == "runtime_instance":
            event = RuntimeEvent.model_validate(record.payload)
            frontend_request_id = self._frontend_request_id(event.runtime_instance_id, event.request_id)
            projected_events = project_runtime_event(
                event,
                request_id=frontend_request_id,
                delegated_task_name=self._delegated_task_name(event.task_id or ""),
            )
        elif record.aggregate_kind == "command":
            projected_events = project_command_event(record)
        elif record.aggregate_kind == "delegated_task":
            projected_events = [project_delegated_task_record(record)]
        else:
            return
        for projected in projected_events:
            self._publish(event_principal_id=principal_id, event=projected)

    def publish_observation(self, instance: RuntimeInstance, chunk: Any) -> None:
        projected = project_runtime_observation(
            instance,
            chunk,
            request_id=self._frontend_request_id(
                instance.runtime_instance_id,
                instance.request.request_id,
            ),
        )
        if not projected:
            return
        with self._lock:
            loop = self._loop
        if loop is None:
            return
        for event in projected:
            loop.call_soon_threadsafe(
                self._publish,
                instance.request.principal_id,
                event,
            )

    def ready_event(self, principal_id: str) -> dict[str, Any]:
        return _frontend_event(
            event_type="runtime_ready",
            request_id=None,
            runtime_instance_id=None,
            session_id=None,
            node_id=None,
            timestamp=None,
            payload={
                "options": {},
                "event_stream_id": self.stream_id,
                "active_requests": self._active_requests(
                    _required_text(principal_id, "principal_id")
                ),
            },
        )

    def _publish(self, event_principal_id: Any, event: dict[str, Any]) -> None:
        principal_id = str(event_principal_id or event.get("payload", {}).get("principal_id") or "").strip()
        with self._lock:
            subscriptions = tuple(self._subscriptions)
        for subscription in subscriptions:
            if principal_id and subscription.principal_id != principal_id:
                continue
            try:
                subscription.queue.put_nowait(event)
            except asyncio.QueueFull:
                with self._lock:
                    self._subscriptions.discard(subscription)


class RuntimeEventFanout:
    def __init__(
        self,
        dynamic_sink: Any,
        frontend_bridge: FrontendEventBridge,
        principal_for_runtime: Callable[[str], str],
    ) -> None:
        self._dynamic_sink = dynamic_sink
        self._frontend_bridge = frontend_bridge
        self._principal_for_runtime = principal_for_runtime

    async def publish(self, record: OutboxRecord) -> None:
        await self._dynamic_sink.publish(record)
        if record.aggregate_kind not in {"runtime_instance", "command", "delegated_task"}:
            return
        if record.aggregate_kind == "runtime_instance":
            principal_id = self._principal_for_runtime(record.aggregate_id)
        elif record.aggregate_kind == "delegated_task":
            task = record.payload.get("task")
            principal_id = str(
                (task.get("principal_id") if isinstance(task, dict) else None)
                or record.payload.get("principal_id")
                or ""
            )
        else:
            principal_id = str(record.payload.get("principal_id") or "")
        await self._frontend_bridge.publish_record(
            record,
            principal_id=principal_id,
        )


def project_delegated_task_record(record: OutboxRecord) -> dict[str, Any]:
    payload = dict(record.payload)
    task = payload.get("task") if isinstance(payload.get("task"), dict) else {}
    event_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    session_id = str(
        payload.get("session_id")
        or event_payload.get("session_id")
        or task.get("session_id")
        or ""
    ).strip() or None
    return _frontend_event(
        event_type="background_task_updated",
        request_id=None,
        runtime_instance_id=str(
            payload.get("child_runtime_instance_id")
            or ""
        ) or None,
        session_id=session_id,
        node_id=None,
        timestamp=record.created_at,
        payload={
            **payload,
            "task_id": payload.get("task_id") or task.get("task_id") or record.aggregate_id,
            "session_id": session_id,
            "event_kind": record.event_kind,
        },
        event_id=record.event_id,
    )


_MODEL_MESSAGE_EVENT_TYPES = frozenset(
    {
        "model_call_started",
        "model_reasoning_delta",
        "model_reasoning_completed",
        "model_stream_delta",
        "model_message_completed",
        "model_generation_interrupted",
    }
)


def project_runtime_observation(
    instance: RuntimeInstance,
    chunk: Any,
    *,
    request_id: str,
) -> list[dict[str, Any]]:
    if not isinstance(chunk, dict):
        return []
    chunk_type = str(chunk.get("type") or "")
    payload = chunk.get("payload")
    if chunk_type == "tool_activity" and isinstance(payload, dict):
        raw_events = payload.get("events")
        if not isinstance(raw_events, list):
            return []
        return [
            _observation_event(instance, event, request_id=request_id)
            for event in raw_events
            if isinstance(event, dict) and str(event.get("event_type") or "").strip()
        ]
    if not isinstance(payload, dict):
        return []
    if chunk_type == "context_event":
        event_type = _observation_event_type(str(payload.get("event_type") or ""))
        event_payload = {
            key: value
            for key, value in payload.items()
            if key != "event_type"
        }
        node_id = str(payload.get("node_id") or "").strip() or None
        timestamp = None
        event_id = uuid4().hex
    elif chunk_type == "node_event":
        event_type = _observation_event_type(str(payload.get("event_type") or ""))
        body = payload.get("payload")
        event_payload = dict(body) if isinstance(body, dict) else {}
        node_id = str(payload.get("node_id") or "").strip() or None
        timestamp = str(payload.get("created_at") or "").strip() or None
        event_id = str(payload.get("event_id") or "").strip() or uuid4().hex
    else:
        return []
    if not event_type:
        return []
    if event_type in _MODEL_MESSAGE_EVENT_TYPES:
        event_payload["visible_to_user"] = fixed_graph_model_output_visible(
            instance.request.strategy,
            node_id,
        )
    shared_payload = {
        **event_payload,
        "workspace_id": instance.request.workspace_id,
        "package_id": "factory_chat",
        "agent_session_id": instance.request.session_id,
        "runtime_role": instance.request.runtime_role,
        "source_task_id": instance.request.task_id,
    }
    projected = [
        _frontend_event(
            event_type=event_type,
            request_id=request_id,
            runtime_instance_id=instance.runtime_instance_id,
            session_id=instance.request.session_id,
            node_id=node_id,
            timestamp=timestamp,
            payload=shared_payload,
            event_id=event_id,
        )
    ]
    projected.extend(
        _message_events_from_model_event(
            event_type=event_type,
            event_payload=shared_payload,
            event_id=event_id,
            request_id=request_id,
            instance=instance,
            node_id=node_id,
            timestamp=timestamp,
        )
    )
    return projected


def _message_events_from_model_event(
    *,
    event_type: str,
    event_payload: dict[str, Any],
    event_id: str,
    request_id: str,
    instance: RuntimeInstance,
    node_id: str | None,
    timestamp: str | None,
) -> list[dict[str, Any]]:
    if event_payload.get("visible_to_user") is False:
        return []
    stream_id = str(event_payload.get("stream_id") or "").strip()
    if not stream_id:
        return []
    common = {
        "request_id": request_id,
        "runtime_instance_id": instance.runtime_instance_id,
        "session_id": instance.request.session_id,
        "node_id": node_id,
        "timestamp": timestamp,
    }
    source = {
        "workspace_id": instance.request.workspace_id,
        "package_id": "factory_chat",
        "agent_session_id": instance.request.session_id,
        "runtime_role": instance.request.runtime_role,
        "source_task_id": instance.request.task_id,
    }
    events: list[dict[str, Any]] = []
    if event_type == "model_call_started":
        events.append(
            _frontend_event(
                event_type="message_started",
                payload={
                    **source,
                    **_message_identity(stream_id),
                    "role": "assistant",
                    "status": "streaming",
                },
                event_id=f"{event_id}:message-started",
                **common,
            )
        )
        return events
    if event_type == "model_reasoning_delta":
        delta = str(event_payload.get("delta") or "")
        if delta:
            events.append(
                _frontend_event(
                    event_type="message_part_delta",
                    payload={
                        **source,
                        **_message_part_identity(stream_id, "reasoning"),
                        "part_status": "streaming",
                        "format": "markdown",
                        "delta": delta,
                        "content_mode": "delta",
                    },
                    event_id=f"{event_id}:message-reasoning-delta",
                    **common,
                )
            )
        return events
    if event_type == "model_reasoning_completed":
        content = str(
            event_payload.get("content")
            or event_payload.get("reasoning_content")
            or ""
        )
        if content:
            events.append(
                _frontend_event(
                    event_type="message_part_completed",
                    payload={
                        **source,
                        **_message_part_identity(stream_id, "reasoning"),
                        "part_status": "completed",
                        "format": "markdown",
                        "content": content,
                    },
                    event_id=f"{event_id}:message-reasoning-completed",
                    **common,
                )
            )
        return events
    if event_type == "model_stream_delta":
        return events
    if event_type == "model_generation_interrupted":
        reasoning_content = str(event_payload.get("reasoning_content") or "")
        content = str(event_payload.get("content") or "")
        if reasoning_content:
            events.append(
                _frontend_event(
                    event_type="message_part_completed",
                    payload={
                        **source,
                        **_message_part_identity(stream_id, "reasoning"),
                        "part_status": "completed",
                        "format": "markdown",
                        "content": reasoning_content,
                    },
                    event_id=f"{event_id}:message-reasoning-interrupted",
                    **common,
                )
            )
        if content:
            events.append(
                _frontend_event(
                    event_type="message_part_completed",
                    payload={
                        **source,
                        **_message_part_identity(stream_id, "text"),
                        "part_status": "completed",
                        "format": "markdown",
                        "content": content,
                    },
                    event_id=f"{event_id}:message-text-interrupted",
                    **common,
                )
            )
        events.append(
            _frontend_event(
                event_type="message_completed",
                payload={
                    **source,
                    **_message_identity(stream_id),
                    "status": "stopped",
                    "discard": not bool(content or reasoning_content),
                    "completion_reason": "user_interrupted",
                },
                event_id=f"{event_id}:message-superseded",
                **common,
            )
        )
        return events
    if event_type != "model_message_completed":
        return []
    reasoning_content = str(event_payload.get("reasoning_content") or "")
    content = (
        ""
        if event_payload.get("presentation") == "activity"
        else str(event_payload.get("content") or "")
    )
    if reasoning_content:
        events.append(
            _frontend_event(
                event_type="message_part_completed",
                payload={
                    **source,
                    **_message_part_identity(stream_id, "reasoning"),
                    "part_status": "completed",
                    "format": "markdown",
                    "content": reasoning_content,
                },
                event_id=f"{event_id}:message-reasoning-completed",
                **common,
            )
        )
    if content:
        events.append(
            _frontend_event(
                event_type="message_part_completed",
                payload={
                    **source,
                    **_message_part_identity(stream_id, "text"),
                    "part_status": "completed",
                    "format": "markdown",
                    "content": content,
                },
                event_id=f"{event_id}:message-text-completed",
                **common,
            )
        )
    if content or reasoning_content:
        events.append(
            _frontend_event(
                event_type="message_completed",
                payload={
                    **source,
                    **_message_identity(stream_id),
                    "status": "completed",
                    "completion_reason": event_payload.get("completion_reason"),
                },
                event_id=f"{event_id}:message-completed",
                **common,
            )
        )
    return events


def _message_identity(stream_id: str) -> dict[str, str]:
    return {"message_id": stream_id, "stream_id": stream_id}


def _message_part_identity(stream_id: str, part_type: str) -> dict[str, str]:
    return {
        **_message_identity(stream_id),
        "part_id": f"{stream_id}:{part_type}",
        "part_type": part_type,
    }


def project_runtime_event(
    event: RuntimeEvent,
    *,
    request_id: str,
    delegated_task_name: str | None = None,
) -> list[dict[str, Any]]:
    kind = event.payload.kind
    mapping = {
        "runtime_queued": "runtime_request_queued",
        "runtime_started": "run_started",
        "runtime_completed": "run_completed",
        "failed": "run_failed",
        "cancelled": "run_cancelled",
        "runtime_cancelling": "runtime_paused",
        "progress": "node_progress",
        "temporary_agent_started": "background_task_started",
    }
    if kind in {"runtime_waiting_approval", "approval_required"}:
        event_type = "tool_approval_requested"
    elif kind in {"runtime_waiting_external", "question"}:
        event_type = "interrupt_requested"
    else:
        event_type = mapping.get(kind)
    if not event_type:
        return []
    payload = event.payload.model_dump(mode="json")
    if event_type == "tool_approval_requested":
        details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
        source = details.get("source") if isinstance(details.get("source"), dict) else {}
        interrupts = details.get("interrupts") if isinstance(details, dict) else []
        interrupt = interrupts[0] if isinstance(interrupts, list) and interrupts and isinstance(interrupts[0], dict) else {}
        nested_requests = interrupt.get("requests") if isinstance(interrupt.get("requests"), list) else []
        requests = [dict(item) for item in nested_requests if isinstance(item, dict)]
        if not requests:
            requests = [{
                "tool_call_id": payload.get("tool_call_id") or interrupt.get("tool_call_id"),
                "tool_id": payload.get("capability_id") or interrupt.get("capability_id") or interrupt.get("tool_id"),
                "tool_name": payload.get("capability_id") or interrupt.get("tool_name") or interrupt.get("tool_id"),
                "summary": payload.get("summary") or interrupt.get("summary") or interrupt.get("message"),
            }]
        payload = {
            **payload,
            "interrupt_id": payload.get("interrupt_id") or interrupt.get("interrupt_id") or interrupt.get("id"),
            "type": payload.get("type") or interrupt.get("type") or "tool_approval",
            "message": payload.get("message") or interrupt.get("message"),
            "choices": payload.get("choices") or interrupt.get("choices"),
            "requests": requests,
            "source_task_id": source.get("task_id"),
            "source_task_name": delegated_task_name,
            "source_runtime_role": source.get("runtime_role"),
            "source_runtime_instance_id": event.runtime_instance_id,
            "parent_runtime_instance_id": source.get("parent_runtime_instance_id"),
        }
    payload.update(
        {
            "workspace_id": event.workspace_id,
            "package_id": "factory_chat",
            "agent_session_id": event.session_id,
            "principal_id": None,
            "runtime_role": event.runtime_role,
            "source_task_id": event.task_id,
            "source_task_name": delegated_task_name,
        }
    )
    return [
        _frontend_event(
            event_type=event_type,
            request_id=request_id,
            runtime_instance_id=event.runtime_instance_id,
            session_id=event.session_id,
            node_id=None,
            timestamp=event.created_at,
            payload=payload,
            event_id=event.event_id,
        )
    ]


def project_command_event(record: OutboxRecord) -> list[dict[str, Any]]:
    raw = dict(record.payload)
    command_kind = str(raw.pop("command_kind", "") or "")
    request_source = str(raw.pop("request_source", "user") or "user")
    dispatch_state = str(raw.pop("dispatch_state", "") or "")
    queue_position = raw.pop("queue_position", None)
    try:
        receipt = CommandReceipt.model_validate(raw)
    except Exception:
        return []
    if (
        record.event_kind == "command_queued"
        and command_kind == "send_message"
        and dispatch_state == "queued"
    ):
        event_type = "runtime_request_queued"
        payload = {"dispatch_state": "queued", "queue_position": queue_position}
    elif record.event_kind == "command_attached_runtime" and command_kind == "send_message":
        event_type = "runtime_request_dispatched"
        payload = {"dispatch_state": "running", "queue_position": 0}
    elif record.event_kind == "command_steering":
        event_type = "runtime_request_steering"
        payload = {"dispatch_state": dispatch_state or "steering", "queue_position": 0}
    elif record.event_kind in {"command_failed", "command_rejected"} and receipt.runtime_instance_id is None:
        event_type = "run_failed"
        payload = {
            "dispatch_state": "failed",
            "message": receipt.rejection_code or "command failed before runtime startup",
            "error": {
                "code": receipt.rejection_code or "command_failed_before_runtime",
                "message": receipt.rejection_code or "command failed before runtime startup",
            },
        }
    elif record.event_kind == "command_cancelled" and receipt.runtime_instance_id is None:
        event_type = "run_cancelled"
        payload = {
            "dispatch_state": "cancelled",
            "reason": "user_cancelled",
        }
    else:
        return []
    payload.update(
        {
            "principal_id": receipt.principal_id,
            "package_id": "factory_chat",
            "agent_session_id": receipt.session_id,
            "request_source": request_source,
        }
    )
    return [
        _frontend_event(
            event_type=event_type,
            request_id=receipt.command_id,
            runtime_instance_id=receipt.runtime_instance_id,
            session_id=receipt.session_id,
            node_id=None,
            timestamp=receipt.updated_at,
            payload=payload,
            event_id=record.event_id,
        )
    ]


def _observation_event(
    instance: RuntimeInstance,
    event: dict[str, Any],
    *,
    request_id: str,
) -> dict[str, Any]:
    event_type = str(event.get("event_type") or "")
    return _frontend_event(
        event_type=event_type,
        request_id=request_id,
        runtime_instance_id=instance.runtime_instance_id,
        session_id=instance.request.session_id,
        node_id=str(event.get("node_id") or "").strip() or None,
        timestamp=None,
        payload={
            **event,
            "workspace_id": instance.request.workspace_id,
            "package_id": "factory_chat",
            "agent_session_id": instance.request.session_id,
            "runtime_role": instance.request.runtime_role,
            "source_task_id": instance.request.task_id,
        },
    )


def _observation_event_type(value: str) -> str:
    return {
        "node_entered": "node_started",
        "node_completed": "node_completed",
        "node_failed": "node_failed",
    }.get(value, value)


def _frontend_event(
    *,
    event_type: str,
    request_id: str | None,
    runtime_instance_id: str | None,
    session_id: str | None,
    node_id: str | None,
    timestamp: str | None,
    payload: dict[str, Any],
    event_id: str | None = None,
) -> dict[str, Any]:
    from datetime import UTC, datetime

    return {
        "event_id": event_id or uuid4().hex,
        "protocol_version": "factory_frontend.v1",
        "event_type": event_type,
        "persistence": "transient" if event_type.endswith("_delta") else "durable",
        "producer_type": "dynamic_runtime",
        "request_id": request_id,
        "run_id": runtime_instance_id,
        "session_id": session_id,
        "thread_id": session_id,
        "mode": "agent_package",
        "graph_id": None,
        "node_id": node_id,
        "node_label": node_id,
        "node_kind": None,
        "stage_id": None,
        "span_id": None,
        "parent_span_id": None,
        "sequence": 0,
        "timestamp": timestamp or datetime.now(UTC).isoformat(),
        "severity": None,
        "message": None,
        "payload": payload,
        "process_event": not event_type.endswith("_delta"),
    }


def _required_text(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text
