from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime
import logging
import os
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
from web_frontend.backend.runtime_event_journal import RuntimeEventJournal
from web_frontend.backend.runtime_event_pipeline import RuntimeEventPipeline

logger = logging.getLogger(__name__)


ALWAYS_LONG_RUNNING_COMMANDS = {
    "send_message",
    "resume_interrupt",
    "initialize_agent_package",
    "send_agent_package_message",
    "run_agent_package",
    "run_agent_evolution",
    "run_agent_group_member",
}

LONG_RUNNING_ACTIONS = {
    "knowledge_manage": {"confirm_source", "reindex"},
    "extensions_manage": {"install_mcp", "test_mcp"},
    "scheduler_manage": {"run_now"},
}

COMMAND_MODE_HINTS = {
    "initialize_agent_package": "agent_package",
    "send_agent_package_message": "agent_package",
    "run_agent_package": "agent_package",
    "run_agent_evolution": "evolve_agent",
    "run_agent_group_member": "agent_group",
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

RUNTIME_EVENT_PIPELINE_CAPACITY_ENV = "AGENTFACTORY_RUNTIME_EVENT_PIPELINE_CAPACITY"
DEFAULT_RUNTIME_EVENT_PIPELINE_CAPACITY = 2048


class RuntimeBridge:
    """Owns the in-process factory runtime and SSE event fan-out."""

    def __init__(self) -> None:
        self.adapter: FactoryRuntimeAdapter | None = None
        self.event_history: deque[dict[str, Any]] = deque(maxlen=500)
        self.event_journal = RuntimeEventJournal()
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.event_observers: set[Callable[[dict[str, Any]], None]] = set()
        self._background_threads: dict[str, threading.Thread] = {}
        self._active_requests: dict[str, dict[str, Any]] = {}
        self._deleting_session_ids: set[str] = set()
        self._background_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._event_pipeline = RuntimeEventPipeline(
            prepare=self._prepare_runtime_event,
            deliver=self._schedule_runtime_event_delivery,
            report_failure=self._report_event_pipeline_failure,
            capacity=_runtime_event_pipeline_capacity(),
        )

    @property
    def active(self) -> bool:
        return self.adapter is not None

    async def start(self) -> None:
        if self.adapter is not None:
            logger.warning("Runtime service already started")
            return

        self._loop = asyncio.get_running_loop()
        self._event_pipeline.start()
        self.adapter = await asyncio.to_thread(FactoryRuntimeAdapter, emit=self._emit_from_runtime)
        self._emit_from_runtime(self._runtime_ready_event())
        logger.info("Runtime service started")

    async def stop(self) -> None:
        adapter = self.adapter
        if adapter is None:
            await asyncio.to_thread(self._event_pipeline.stop, drain=True)
            self._loop = None
            logger.info("Runtime service already stopped")
            return

        shutdown_cmd = FactoryFrontendCommand(
            type="shutdown",
            request_id=str(uuid.uuid4()),
        )
        await asyncio.to_thread(adapter.handle, shutdown_cmd)
        self.adapter = None
        await asyncio.to_thread(self._event_pipeline.stop, drain=True)
        self._loop = None
        with self._background_lock:
            self._background_threads.clear()
            self._active_requests.clear()
            self._deleting_session_ids.clear()
        logger.info("Runtime service stopped")

    async def send_frontend_command(self, command: FactoryFrontendCommand) -> None:
        if self.adapter is None:
            raise RuntimeError("Runtime service not started")

        command = self._resolve_cancel_command(command)
        if _is_long_running_command(command):
            self._start_background(command)
            return

        if command.type in {"delete_session", "delete_agent_package_session"}:
            await self._cancel_and_join_deleted_session_requests(command)
            return
        await asyncio.to_thread(self._handle_command, command)

    async def send_and_wait(
        self,
        command: FactoryFrontendCommand,
        *,
        event_types: set[str],
        timeout_seconds: float | None = 30.0,
        event_filter: Callable[[dict[str, Any]], bool] | None = None,
    ) -> dict[str, Any]:
        event_queue = self.subscribe(replay_history=False)
        try:
            await self.send_frontend_command(command)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout_seconds if timeout_seconds is not None else None
            while True:
                remaining = deadline - loop.time() if deadline is not None else None
                if remaining is not None and remaining <= 0:
                    raise HTTPException(status_code=504, detail=f"Timed out waiting for {command.type}")
                try:
                    event_payload = (
                        await event_queue.get()
                        if remaining is None
                        else await asyncio.wait_for(event_queue.get(), timeout=remaining)
                    )
                except TimeoutError as exc:
                    raise HTTPException(status_code=504, detail=f"Timed out waiting for {command.type}") from exc
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

    def subscribe(
        self,
        *,
        replay_history: bool = True,
        after_event_id: str | None = None,
    ) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        replay_gap = False
        if replay_history:
            history = list(self.event_history)
            if after_event_id:
                cursor_index = next(
                    (
                        index
                        for index, item in enumerate(history)
                        if str(item.get("event_id") or "") == after_event_id
                    ),
                    -1,
                )
                replay_gap = cursor_index < 0
                history = history[cursor_index + 1 :] if cursor_index >= 0 else []
            for event_payload in history:
                queue.put_nowait(event_payload)
        snapshot = self._runtime_ready_event(
            replay_gap=replay_gap,
            replay_after_event_id=after_event_id,
        )
        if snapshot is not None:
            queue.put_nowait(snapshot.model_dump(mode="json"))
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self.subscribers.discard(queue)

    def add_event_observer(self, observer: Callable[[dict[str, Any]], None]) -> None:
        self.event_observers.add(observer)

    def remove_event_observer(self, observer: Callable[[dict[str, Any]], None]) -> None:
        self.event_observers.discard(observer)

    def _start_background(self, command: FactoryFrontendCommand) -> None:
        request_id = command.request_id or f"{command.type}-{id(command)}"
        with self._background_lock:
            session_id = _command_session_id(command)
            if session_id and session_id in self._deleting_session_ids:
                raise RuntimeError(f"session is being deleted: {session_id}")
            predecessors = [
                thread
                for active_request_id, thread in self._background_threads.items()
                if active_request_id != request_id
                and session_id
                and _active_request_session_id(self._active_requests.get(active_request_id)) == session_id
                and not bool(self._active_requests.get(active_request_id, {}).get("background"))
            ]
            request = _active_request_from_command(command, request_id)
            request["payload"]["dispatch_state"] = "queued" if predecessors else "running"
            self._active_requests[request_id] = request
            thread = threading.Thread(
                target=self._run_background_command,
                args=(command, request_id, predecessors),
                name=f"factory-runtime-command-{request_id}",
                daemon=True,
            )
            self._background_threads[request_id] = thread
            thread.start()

    async def _cancel_and_join_deleted_session_requests(
        self,
        command: FactoryFrontendCommand,
    ) -> None:
        session_id = _deleted_session_id(command)
        if not session_id:
            await asyncio.to_thread(self._handle_command, command)
            return
        with self._background_lock:
            self._deleting_session_ids.add(session_id)
            active = [
                (request_id, thread)
                for request_id, thread in self._background_threads.items()
                if _active_request_session_id(self._active_requests.get(request_id)) == session_id
            ]
        try:
            for request_id, _thread in active:
                cancel_command = self._resolve_cancel_command(
                    FactoryFrontendCommand(
                        type="cancel_runtime_request",
                        request_id=f"{command.request_id or uuid.uuid4().hex}:cancel:{request_id}",
                        session_id=session_id,
                        mode=command.mode,
                        payload={
                            "target_request_id": request_id,
                            "reason": "session_deleted",
                        },
                    )
                )
                await asyncio.to_thread(self._handle_command, cancel_command)
            if active:
                await asyncio.gather(
                    *(asyncio.to_thread(thread.join) for _request_id, thread in active)
                )
            await asyncio.to_thread(self._handle_command, command)
        finally:
            with self._background_lock:
                self._deleting_session_ids.discard(session_id)

    def _run_background_command(
        self,
        command: FactoryFrontendCommand,
        request_id: str,
        predecessors: list[threading.Thread],
    ) -> None:
        try:
            for predecessor in predecessors:
                predecessor.join()
            with self._background_lock:
                active_request = self._active_requests.get(request_id)
                if active_request is None or active_request.get("payload", {}).get("cancel_requested_at"):
                    return
                active_request["payload"]["dispatch_state"] = "running"
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

    def _resolve_cancel_command(self, command: FactoryFrontendCommand) -> FactoryFrontendCommand:
        if command.type != "cancel_runtime_request":
            return command
        payload = dict(command.payload or {})
        requested_target = str(payload.get("target_request_id") or "").strip()
        session_id = _command_session_id(command)
        resolved_target = ""
        with self._background_lock:
            if requested_target and requested_target in self._active_requests:
                resolved_target = requested_target
            else:
                candidates = [
                    request
                    for request in self._active_requests.values()
                    if not bool(request.get("background"))
                    and session_id
                    and _active_request_session_id(request) == session_id
                ]
                if candidates:
                    active_request = max(candidates, key=lambda item: str(item.get("startedAt") or ""))
                    resolved_target = str(active_request.get("requestId") or "").strip()
            if resolved_target and resolved_target in self._active_requests:
                active_payload = self._active_requests[resolved_target].setdefault("payload", {})
                active_payload["cancel_requested_at"] = datetime.now(UTC).isoformat()
        if not resolved_target:
            return command
        if requested_target and requested_target != resolved_target:
            payload["requested_target_request_id"] = requested_target
        payload["target_request_id"] = resolved_target
        return command.model_copy(update={"payload": payload})

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
        self._event_pipeline.submit(event_payload)

    def _prepare_runtime_event(self, event_payload: dict[str, Any]) -> dict[str, Any]:
        try:
            event_payload = self.event_journal.prepare_for_delivery(event_payload)
        except Exception:
            logger.exception("Failed to persist or hydrate runtime process event")
        try:
            record_model_usage_frontend_event(event_payload)
        except Exception:
            logger.exception("Failed to record model usage event")
        for observer in tuple(self.event_observers):
            try:
                observer(event_payload)
            except Exception:
                logger.exception("Runtime event observer failed")
        return event_payload

    def _schedule_runtime_event_delivery(self, event_payload: dict[str, Any]) -> None:
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

    def schedule_coroutine(self, coroutine: Any) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            close = getattr(coroutine, "close", None)
            if callable(close):
                close()
            return
        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        future.add_done_callback(_log_scheduled_coroutine_failure)

    def _report_event_pipeline_failure(self, stage: str, exc: BaseException) -> None:
        logger.error(
            "Runtime event pipeline %s failed: %s: %s",
            stage,
            type(exc).__name__,
            exc,
            exc_info=(type(exc), exc, exc.__traceback__),
        )

    def _runtime_ready_event(
        self,
        *,
        replay_gap: bool = False,
        replay_after_event_id: str | None = None,
    ):
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
                "event_replay": {
                    "gap": replay_gap,
                    "after_event_id": replay_after_event_id,
                },
                "event_pipeline": self._event_pipeline.stats().payload(),
            },
        )

    def _active_request_payloads(self) -> list[dict[str, Any]]:
        with self._background_lock:
            return [
                dict(item)
                for item in self._active_requests.values()
                if not item.get("payload", {}).get("cancel_requested_at")
            ]

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


def _runtime_event_pipeline_capacity() -> int:
    raw = str(os.getenv(RUNTIME_EVENT_PIPELINE_CAPACITY_ENV) or "").strip()
    if not raw:
        return DEFAULT_RUNTIME_EVENT_PIPELINE_CAPACITY
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{RUNTIME_EVENT_PIPELINE_CAPACITY_ENV} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{RUNTIME_EVENT_PIPELINE_CAPACITY_ENV} must be greater than zero")
    return value


def _log_scheduled_coroutine_failure(future: Any) -> None:
    try:
        future.result()
    except BaseException:
        logger.exception("Runtime event observer coroutine failed")


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


def _command_session_id(command: FactoryFrontendCommand) -> str:
    return str(command.session_id or command.payload.get("session_id") or "").strip()


def _deleted_session_id(command: FactoryFrontendCommand) -> str:
    if command.type == "delete_agent_package_session":
        return str(command.payload.get("session_id") or command.session_id or "").strip()
    return _command_session_id(command)


def _active_request_session_id(request: dict[str, Any] | None) -> str:
    if not request:
        return ""
    payload = request.get("payload") if isinstance(request.get("payload"), dict) else {}
    return str(request.get("sessionId") or payload.get("session_id") or "").strip()


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
