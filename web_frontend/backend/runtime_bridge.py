from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime
import logging
import threading
import uuid
from typing import Any, Callable

from fastapi import HTTPException

from agent_factory.factory_graph.frontend_bridge.protocol import (
    FactoryFrontendCommand,
    event,
)
from agent_factory.model_pool.usage import record_model_usage_frontend_event
from agent_factory.factory_graph.frontend_bridge.runtime_adapter import FactoryRuntimeAdapter

logger = logging.getLogger(__name__)


ALWAYS_LONG_RUNNING_COMMANDS = {
    "send_message",
    "resume_interrupt",
    "initialize_agent_package",
    "send_agent_package_message",
    "run_agent_package",
    "run_agent_evolution",
}

LONG_RUNNING_ACTIONS = {
    "knowledge_manage": {"confirm_source", "reindex"},
    "extensions_manage": {"test_mcp"},
    "scheduler_manage": {"run_now"},
}

COMMAND_MODE_HINTS = {
    "initialize_agent_package": "agent_package",
    "send_agent_package_message": "agent_package",
    "run_agent_package": "agent_package",
    "run_agent_evolution": "evolve_agent",
}

ACTIVE_REQUEST_METADATA_EVENTS = {
    "run_started",
    "session_started",
    "session_switched",
    "agent_package_selected",
    "agent_package_session_loaded",
    "mode_changed",
    "runtime_resumed",
    "interrupt_requested",
}

TERMINAL_REQUEST_EVENTS = {
    "run_completed",
    "run_cancelled",
    "run_failed",
    "error",
}


class RuntimeBridge:
    """Owns the in-process factory runtime and SSE event fan-out."""

    def __init__(self) -> None:
        self.adapter: FactoryRuntimeAdapter | None = None
        self.event_history: deque[dict[str, Any]] = deque(maxlen=500)
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._background_threads: dict[str, threading.Thread] = {}
        self._active_requests: dict[str, dict[str, Any]] = {}
        self._background_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def active(self) -> bool:
        return self.adapter is not None

    async def start(self) -> None:
        if self.adapter is not None:
            logger.warning("Runtime service already started")
            return

        self._loop = asyncio.get_running_loop()
        self.adapter = await asyncio.to_thread(FactoryRuntimeAdapter, emit=self._emit_from_runtime)
        self._emit_from_runtime(self._runtime_ready_event())
        logger.info("Runtime service started")

    async def stop(self) -> None:
        adapter = self.adapter
        if adapter is None:
            logger.info("Runtime service already stopped")
            return

        shutdown_cmd = FactoryFrontendCommand(
            type="shutdown",
            request_id=str(uuid.uuid4()),
        )
        await asyncio.to_thread(adapter.handle, shutdown_cmd)
        self.adapter = None
        self._loop = None
        with self._background_lock:
            self._background_threads.clear()
            self._active_requests.clear()
        logger.info("Runtime service stopped")

    async def send_frontend_command(self, command: FactoryFrontendCommand) -> None:
        if self.adapter is None:
            raise RuntimeError("Runtime service not started")

        if _is_long_running_command(command):
            self._start_background(command)
            return

        await asyncio.to_thread(self._handle_command, command)

    async def send_and_wait(
        self,
        command: FactoryFrontendCommand,
        *,
        event_types: set[str],
        timeout_seconds: float = 30.0,
        event_filter: Callable[[dict[str, Any]], bool] | None = None,
    ) -> dict[str, Any]:
        event_queue = self.subscribe(replay_history=False)
        try:
            await self.send_frontend_command(command)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout_seconds
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise HTTPException(status_code=504, detail=f"Timed out waiting for {command.type}")
                event_payload = await asyncio.wait_for(event_queue.get(), timeout=remaining)
                if event_payload.get("request_id") != command.request_id:
                    continue
                if event_payload.get("event_type") == "error":
                    raise HTTPException(
                        status_code=400,
                        detail=event_payload.get("message") or "Runtime command failed",
                    )
                if event_payload.get("event_type") in event_types and (
                    event_filter is None or event_filter(event_payload)
                ):
                    return event_payload
        finally:
            self.unsubscribe(event_queue)

    def subscribe(self, *, replay_history: bool = True) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        if replay_history:
            for event_payload in self.event_history:
                queue.put_nowait(event_payload)
            snapshot = self._runtime_ready_event()
            if snapshot is not None:
                queue.put_nowait(snapshot.model_dump(mode="json"))
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self.subscribers.discard(queue)

    def _start_background(self, command: FactoryFrontendCommand) -> None:
        request_id = command.request_id or f"{command.type}-{id(command)}"
        with self._background_lock:
            self._active_requests[request_id] = _active_request_from_command(command, request_id)
            thread = threading.Thread(
                target=self._run_background_command,
                args=(command, request_id),
                name=f"factory-runtime-command-{request_id}",
                daemon=True,
            )
            self._background_threads[request_id] = thread
            thread.start()

    def _run_background_command(self, command: FactoryFrontendCommand, request_id: str) -> None:
        try:
            self._handle_command(command)
        except Exception as exc:
            logger.exception("Runtime command failed in background: %s", command.type)
            self._emit_from_runtime(
                event(
                    "error",
                    request_id=command.request_id,
                    message=f"{type(exc).__name__}: {exc}",
                )
            )
        finally:
            with self._background_lock:
                self._background_threads.pop(request_id, None)
                self._active_requests.pop(request_id, None)

    def _handle_command(self, command: FactoryFrontendCommand) -> None:
        adapter = self.adapter
        if adapter is None:
            raise RuntimeError("Runtime service not started")
        adapter.handle(command)

    def _emit_from_runtime(self, payload: Any) -> None:
        if hasattr(payload, "model_dump"):
            event_payload = payload.model_dump(mode="json")
        else:
            event_payload = payload
        if not isinstance(event_payload, dict):
            logger.warning("Ignored non-object runtime event: %r", event_payload)
            return

        self._observe_runtime_event(event_payload)
        loop = self._loop
        if loop is None or loop.is_closed():
            self.event_history.append(event_payload)
            return
        loop.call_soon_threadsafe(self._record_and_broadcast, event_payload)

    def _record_and_broadcast(self, event_payload: dict[str, Any]) -> None:
        try:
            record_model_usage_frontend_event(event_payload)
        except Exception:
            logger.exception("Failed to record model usage event")
        self.event_history.append(event_payload)
        stale_subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        for queue in list(self.subscribers):
            try:
                queue.put_nowait(event_payload)
            except asyncio.QueueFull:
                stale_subscribers.append(queue)
        for queue in stale_subscribers:
            self.unsubscribe(queue)

    def _runtime_ready_event(self):
        adapter = self.adapter
        if adapter is None:
            return None
        return event(
            "runtime_ready",
            producer_type="factory_bridge",
            message="factory runtime service ready",
            graph_id="factory_bridge",
            payload={
                "checkpointer": adapter.checkpointer_payload(),
                "options": adapter._options_payload(),
                "active_requests": self._active_request_payloads(),
            },
        )

    def _active_request_payloads(self) -> list[dict[str, Any]]:
        with self._background_lock:
            return [dict(item) for item in self._active_requests.values()]

    def _observe_runtime_event(self, event_payload: dict[str, Any]) -> None:
        request_id = str(event_payload.get("request_id") or "").strip()
        if not request_id:
            return
        event_type = str(event_payload.get("event_type") or "")
        if event_type in TERMINAL_REQUEST_EVENTS:
            with self._background_lock:
                self._active_requests.pop(request_id, None)
            return
        if event_type not in ACTIVE_REQUEST_METADATA_EVENTS:
            return
        with self._background_lock:
            record = self._active_requests.get(request_id)
            if record is None:
                record = _active_request_from_event(event_payload, request_id)
                self._active_requests[request_id] = record
            _merge_active_request_event(record, event_payload)


def _is_long_running_command(command: FactoryFrontendCommand) -> bool:
    if command.type in ALWAYS_LONG_RUNNING_COMMANDS:
        return True
    long_running_actions = LONG_RUNNING_ACTIONS.get(command.type)
    if not long_running_actions:
        return False
    action = str(command.payload.get("action") or "").strip()
    return action in long_running_actions


def _active_request_from_command(command: FactoryFrontendCommand, request_id: str) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    payload = dict(command.payload or {})
    if command.message:
        payload.setdefault("message", command.message)
    if command.session_id:
        payload.setdefault("session_id", command.session_id)
    payload.setdefault("command_type", command.type)
    return {
        "requestId": request_id,
        "status": "running",
        "mode": command.mode or COMMAND_MODE_HINTS.get(command.type),
        "runId": None,
        "sessionId": command.session_id,
        "commandType": command.type,
        "background": request_id.startswith("scheduler-"),
        "source": "scheduler" if request_id.startswith("scheduler-") else "user",
        "startedAt": now,
        "completedAt": None,
        "payload": payload,
    }


def _active_request_from_event(event_payload: dict[str, Any], request_id: str) -> dict[str, Any]:
    timestamp = str(event_payload.get("timestamp") or datetime.now(UTC).isoformat())
    payload = dict(event_payload.get("payload") or {})
    return {
        "requestId": request_id,
        "status": "running",
        "mode": event_payload.get("mode"),
        "runId": event_payload.get("run_id"),
        "sessionId": event_payload.get("session_id") or payload.get("session_id"),
        "commandType": payload.get("command_type"),
        "background": request_id.startswith("scheduler-"),
        "source": "scheduler" if request_id.startswith("scheduler-") else "user",
        "startedAt": timestamp,
        "completedAt": None,
        "payload": payload,
    }


def _merge_active_request_event(record: dict[str, Any], event_payload: dict[str, Any]) -> None:
    payload = dict(event_payload.get("payload") or {})
    record["mode"] = event_payload.get("mode") or record.get("mode")
    record["runId"] = event_payload.get("run_id") or record.get("runId")
    session_id = event_payload.get("session_id") or payload.get("session_id") or record.get("sessionId")
    record["sessionId"] = session_id
    if session_id:
        payload.setdefault("session_id", session_id)
    record["payload"] = {
        **(record.get("payload") or {}),
        **payload,
    }
