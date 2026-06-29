from __future__ import annotations

import errno
import json
import sys
import threading
from typing import Any

from pydantic import ValidationError

from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendCommand, event
from agent_factory.factory_graph.frontend_bridge.runtime_adapter import FactoryRuntimeAdapter


LONG_RUNNING_COMMANDS = {
    "send_message",
    "resume_interrupt",
    "run_agent_package",
    "run_agent_evolution",
    "scheduler_manage",
}


def main() -> None:
    writer = _JsonLineWriter()
    adapter = FactoryRuntimeAdapter(emit=writer.write)
    dispatcher = _CommandDispatcher(adapter=adapter, writer=writer)
    writer.write(
        event(
            "runtime_ready",
            producer_type="factory_bridge",
            message="factory runtime bridge ready",
            graph_id="factory_bridge",
            payload={"checkpointer": adapter.checkpointer_payload()},
        )
    )
    for line in sys.stdin:
        if writer.closed:
            break
        raw = line.strip()
        if not raw:
            continue
        try:
            command = FactoryFrontendCommand.model_validate_json(raw)
        except ValidationError as exc:
            writer.write(event("error", message=f"invalid command: {exc}"))
            continue
        should_continue = dispatcher.handle(command)
        if not should_continue or writer.closed:
            break
    dispatcher.join()


class _CommandDispatcher:
    def __init__(self, *, adapter: FactoryRuntimeAdapter, writer: "_JsonLineWriter") -> None:
        self.adapter = adapter
        self.writer = writer
        self._lock = threading.Lock()
        self._active_thread: threading.Thread | None = None
        self._active_request_id: str | None = None

    def handle(self, command: FactoryFrontendCommand) -> bool:
        if self.writer.closed:
            return False
        if command.type == "shutdown":
            self.adapter.handle(command)
            return False
        if command.type == "cancel_runtime_request":
            self.adapter.handle(command)
            return True
        if command.type in LONG_RUNNING_COMMANDS:
            return self._start_long_running(command)
        if self._has_active_request():
            self.writer.write(
                event(
                    "error",
                    request_id=command.request_id,
                    message="runtime is busy; cancel the active request before sending another command",
                    payload={"active_request_id": self._active_request_id},
                )
            )
            return True
        self.adapter.handle(command)
        return True

    def join(self) -> None:
        thread = self._active_thread
        if thread is not None:
            thread.join(timeout=0.2)

    def _start_long_running(self, command: FactoryFrontendCommand) -> bool:
        if self.writer.closed:
            return False
        with self._lock:
            if self._active_thread is not None and self._active_thread.is_alive():
                self.writer.write(
                    event(
                        "error",
                        request_id=command.request_id,
                        message="runtime is already handling a request",
                        payload={"active_request_id": self._active_request_id},
                    )
                )
                return True
            self._active_request_id = command.request_id
            self._active_thread = threading.Thread(
                target=self._run_command,
                args=(command,),
                name=f"factory-frontend-command-{command.request_id or command.type}",
                daemon=True,
            )
            self._active_thread.start()
        return True

    def _run_command(self, command: FactoryFrontendCommand) -> None:
        try:
            self.adapter.handle(command)
        finally:
            with self._lock:
                if self._active_request_id == command.request_id:
                    self._active_request_id = None
                self._active_thread = None

    def _has_active_request(self) -> bool:
        with self._lock:
            return self._active_thread is not None and self._active_thread.is_alive()


class _JsonLineWriter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._closed = False

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def write(self, payload: Any) -> None:
        if hasattr(payload, "model_dump"):
            data = payload.model_dump(mode="json")
        else:
            data = payload
        with self._lock:
            if self._closed:
                return
            try:
                sys.stdout.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")
                sys.stdout.flush()
            except BrokenPipeError:
                self._closed = True
            except OSError as exc:
                if exc.errno != errno.EPIPE:
                    raise
                self._closed = True


if __name__ == "__main__":
    main()
