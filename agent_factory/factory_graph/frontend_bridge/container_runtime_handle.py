from __future__ import annotations

from collections import deque
from collections.abc import Callable
import json
import subprocess
import threading
import time
from typing import Any, Deque, Iterator
from uuid import uuid4

from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent, event
from agent_factory.factory_graph.frontend_bridge.runtime_events import (
    heartbeat_due,
    is_terminal_request_event,
    request_heartbeat_event,
    request_timed_out,
    request_timeout_payload,
    run_failed_event,
)
from agent_factory.package_runtime.request_lifecycle import RuntimeRequestPolicy


Emit = Callable[[FactoryFrontendEvent], None]
ContainerStreamItem = tuple[str, Any]


def _target_request_ids(
    events: dict[str, Deque[ContainerStreamItem]],
    request_sessions: dict[str, str],
    *,
    request_id: str | None,
    session_id: str | None,
) -> list[str]:
    target = (request_id or "").strip()
    if target:
        return [target] if target in events else []
    session_target = (session_id or "").strip()
    if session_target:
        return [
            active_request_id
            for active_request_id in events
            if request_sessions.get(active_request_id) == session_target
        ]
    return list(events)


def _command_session_id(command: dict[str, Any]) -> str:
    payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
    return str(payload.get("session_id") or command.get("session_id") or "").strip()


class AgentRuntimeContainerHandle:
    def __init__(
        self,
        *,
        package_id: str,
        package_fingerprint: str,
        idle_timeout_seconds: int,
        request_policy: RuntimeRequestPolicy,
        command: list[str],
        emit: Emit | None = None,
    ) -> None:
        self.package_id = package_id
        self.package_fingerprint = package_fingerprint
        self.idle_timeout_seconds = idle_timeout_seconds
        self.request_policy = request_policy
        self._idle_timer: threading.Timer | None = None
        self._emit = emit
        self._condition = threading.Condition()
        self._stdin_lock = threading.Lock()
        self._request_events: dict[str, Deque[ContainerStreamItem]] = {}
        self._request_commands: dict[str, str] = {}
        self._request_session_ids: dict[str, str] = {}
        self._reader_error: BaseException | None = None
        self._stdout_closed = False
        self._closing = False
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self.startup_payload: dict[str, Any] | None = None
        self.last_used = time.monotonic()
        self._reader_thread = threading.Thread(
            target=self._read_stdout,
            name=f"agent-runtime-stdout-{package_id}",
            daemon=True,
        )
        self._reader_thread.start()
        self._schedule_idle_shutdown()

    def set_emit(self, emit: Emit | None) -> None:
        self._emit = emit

    @property
    def is_running(self) -> bool:
        return self.process.poll() is None

    @property
    def active_request_count(self) -> int:
        with self._condition:
            return len(self._request_events)

    @property
    def active_command_types(self) -> tuple[str, ...]:
        with self._condition:
            return tuple(self._request_commands.values())

    def is_idle(self, timeout_seconds: int) -> bool:
        return timeout_seconds > 0 and (time.monotonic() - self.last_used) > timeout_seconds

    def send(self, command: dict[str, Any]) -> Iterator[tuple[str, Any]]:
        if not self.is_running:
            raise RuntimeError(f"agent runtime container for {self.package_id} is not running")
        if self.process.stdin is None:
            raise RuntimeError("agent runtime container stdio is unavailable")
        request_id = str(command.get("request_id") or uuid4().hex)
        command["request_id"] = request_id
        with self._condition:
            if request_id in self._request_events:
                raise RuntimeError(f"agent runtime request is already active: {request_id}")
            self._request_events[request_id] = deque()
            self._request_commands[request_id] = str(command.get("type") or "")
            session_id = _command_session_id(command)
            if session_id:
                self._request_session_ids[request_id] = session_id
        self._write_command(command)
        self.last_used = time.monotonic()
        self._cancel_idle_shutdown()
        terminal_seen = False
        started_at = time.monotonic()
        last_heartbeat_at = started_at
        try:
            while not terminal_seen:
                batch = self._next_request_batch(request_id)
                for stream_mode, item in batch:
                    yield stream_mode, item
                    if is_terminal_request_event(item, request_id):
                        terminal_seen = True
                if terminal_seen:
                    return
                now = time.monotonic()
                if request_timed_out(started_at, now, self.request_policy):
                    payload = request_timeout_payload(
                        package_id=self.package_id,
                        request_id=request_id,
                        elapsed_seconds=now - started_at,
                        timeout_seconds=self.request_policy.timeout_seconds,
                    )
                    self.close()
                    yield "frontend_event", run_failed_event(request_id, payload)
                    return
                if heartbeat_due(last_heartbeat_at, now, self.request_policy):
                    last_heartbeat_at = now
                    yield "frontend_event", request_heartbeat_event(
                        request_id,
                        package_id=self.package_id,
                        elapsed_seconds=now - started_at,
                        timeout_seconds=self.request_policy.timeout_seconds,
                    )
        finally:
            with self._condition:
                self._request_events.pop(request_id, None)
                self._request_commands.pop(request_id, None)
                self._request_session_ids.pop(request_id, None)
            self.last_used = time.monotonic()
            self._schedule_idle_shutdown()

    def cancel_active_requests(
        self,
        *,
        reason: str,
        request_id: str | None = None,
        session_id: str | None = None,
        visible_output: Any = None,
    ) -> int:
        with self._condition:
            request_ids = _target_request_ids(
                self._request_events,
                self._request_session_ids,
                request_id=request_id,
                session_id=session_id,
            )
        if not request_ids:
            return 0
        try:
            for active_request_id in request_ids:
                self._write_command(
                    {
                        "type": "cancel_runtime_request",
                        "request_id": uuid4().hex,
                        "payload": {
                            "reason": reason,
                            "target_request_id": active_request_id,
                            "visible_output": visible_output,
                        },
                    }
                )
        except Exception as exc:
            self._emit_background_event(
                event(
                    "debug_patch",
                    mode="agent_package",
                    graph_id="agent_package_runtime",
                    producer_type="agent_runtime_host",
                    severity="error",
                    payload={
                        "source": "runtime_request_cancel",
                        "package_id": self.package_id,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
            )
            return 0
        return len(request_ids)

    def close(self) -> None:
        self._cancel_idle_shutdown()
        self._closing = True
        if self.process.stdin is not None and self.is_running:
            try:
                self._write_command({"type": "shutdown", "request_id": uuid4().hex})
            except Exception:
                pass
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        with self._condition:
            self._stdout_closed = True
            self._condition.notify_all()
        self._reader_thread.join(timeout=1)
        self._close_stdio()

    def _next_request_batch(self, request_id: str) -> list[ContainerStreamItem]:
        while True:
            with self._condition:
                queue = self._request_events.get(request_id)
                if queue is None:
                    return []
                if queue:
                    batch = list(queue)
                    queue.clear()
                    return batch
                if self._reader_error is not None:
                    raise RuntimeError(f"agent runtime stdout reader failed: {self._reader_error}") from self._reader_error
                if self._stdout_closed:
                    return_code = self.process.poll()
                    raise RuntimeError(f"agent runtime container exited with {return_code}")
                self._condition.wait(timeout=0.2)
                return []

    def _read_stdout(self) -> None:
        try:
            if self.process.stdout is None:
                raise RuntimeError("agent runtime container stdout is unavailable")
            for line in self.process.stdout:
                stripped = line.strip()
                if not stripped:
                    continue
                self.last_used = time.monotonic()
                try:
                    item = FactoryFrontendEvent.model_validate_json(stripped)
                except Exception:
                    self._dispatch_stderr(stripped)
                    continue
                self._dispatch_event(item)
        except BaseException as exc:
            with self._condition:
                if not self._closing:
                    self._reader_error = exc
                self._condition.notify_all()
        finally:
            with self._condition:
                self._stdout_closed = True
                self._condition.notify_all()

    def _dispatch_event(self, item: FactoryFrontendEvent) -> None:
        background_event: FactoryFrontendEvent | None = None
        with self._condition:
            queue = self._request_events.get(str(item.request_id or ""))
            if queue is not None:
                queue.append(("frontend_event", item))
                self._condition.notify_all()
                return
            background_event = item
        self._emit_background_event(background_event)

    def _dispatch_stderr(self, value: str) -> None:
        background_stderr = True
        with self._condition:
            active_request_ids = list(self._request_events)
            if len(active_request_ids) == 1:
                self._request_events[active_request_ids[0]].append(("stderr", value))
                self._condition.notify_all()
                background_stderr = False
        if background_stderr:
            self._emit_background_event(
                event(
                    "debug_patch",
                    mode="agent_package",
                    graph_id="agent_package_runtime",
                    producer_type="agent_runtime_host",
                    payload={"agent_package_stderr": value, "package_id": self.package_id},
                )
            )

    def _emit_background_event(self, item: FactoryFrontendEvent) -> None:
        if self._emit is not None:
            self._emit(item)
        if not self._request_events:
            self._schedule_idle_shutdown()

    def _write_command(self, command: dict[str, Any]) -> None:
        if self.process.stdin is None:
            raise RuntimeError("agent runtime container stdio is unavailable")
        with self._stdin_lock:
            self.process.stdin.write(json.dumps(command, ensure_ascii=False) + "\n")
            self.process.stdin.flush()

    def _schedule_idle_shutdown(self) -> None:
        self._cancel_idle_shutdown()
        if self.idle_timeout_seconds <= 0 or not self.is_running:
            return
        self._idle_timer = threading.Timer(self.idle_timeout_seconds, self.close)
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def _cancel_idle_shutdown(self) -> None:
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None

    def _close_stdio(self) -> None:
        for stream in (self.process.stdin, self.process.stdout):
            if stream is None:
                continue
            try:
                stream.close()
            except Exception:
                pass
