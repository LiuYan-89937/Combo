from __future__ import annotations

import asyncio
from collections import deque
import logging
import threading
import uuid
from typing import Any

from fastapi import HTTPException

from agent_factory.factory_graph.frontend_bridge.protocol import (
    FactoryFrontendCommand,
    event,
)
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


class RuntimeBridge:
    """Owns the in-process factory runtime and SSE event fan-out."""

    def __init__(self) -> None:
        self.adapter: FactoryRuntimeAdapter | None = None
        self.event_history: deque[dict[str, Any]] = deque(maxlen=500)
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._background_threads: dict[str, threading.Thread] = {}
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
        self._emit_from_runtime(
            event(
                "runtime_ready",
                producer_type="factory_bridge",
                message="factory runtime service ready",
                graph_id="factory_bridge",
                payload={
                    "checkpointer": self.adapter.checkpointer_payload(),
                    "options": self.adapter._options_payload(),
                },
            )
        )
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
                if event_payload.get("event_type") in event_types:
                    return event_payload
        finally:
            self.unsubscribe(event_queue)

    def subscribe(self, *, replay_history: bool = True) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        if replay_history:
            for event_payload in self.event_history:
                queue.put_nowait(event_payload)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self.subscribers.discard(queue)

    def _start_background(self, command: FactoryFrontendCommand) -> None:
        request_id = command.request_id or f"{command.type}-{id(command)}"
        with self._background_lock:
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

        loop = self._loop
        if loop is None or loop.is_closed():
            self.event_history.append(event_payload)
            return
        loop.call_soon_threadsafe(self._record_and_broadcast, event_payload)

    def _record_and_broadcast(self, event_payload: dict[str, Any]) -> None:
        self.event_history.append(event_payload)
        stale_subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        for queue in list(self.subscribers):
            try:
                queue.put_nowait(event_payload)
            except asyncio.QueueFull:
                stale_subscribers.append(queue)
        for queue in stale_subscribers:
            self.unsubscribe(queue)


def _is_long_running_command(command: FactoryFrontendCommand) -> bool:
    if command.type in ALWAYS_LONG_RUNNING_COMMANDS:
        return True
    long_running_actions = LONG_RUNNING_ACTIONS.get(command.type)
    if not long_running_actions:
        return False
    action = str(command.payload.get("action") or "").strip()
    return action in long_running_actions
