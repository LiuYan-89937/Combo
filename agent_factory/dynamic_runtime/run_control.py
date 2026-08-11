from __future__ import annotations

import threading
from collections.abc import Callable
from uuid import uuid4

class RuntimeRunControl:
    """Cooperative graph cancellation with active tool-I/O hooks."""

    __slots__ = (
        "_drain_event",
        "_drain_reason",
        "_tool_cancel_callbacks",
        "_tool_cancel_lock",
    )

    def __init__(self) -> None:
        self._drain_event = threading.Event()
        self._drain_reason: str | None = None
        self._tool_cancel_lock = threading.RLock()
        self._tool_cancel_callbacks: dict[str, Callable[[], None]] = {}

    def request_drain(self, reason: str = "shutdown") -> None:
        drain_reason = _required_text(reason, "reason")
        with self._tool_cancel_lock:
            if self._drain_event.is_set():
                return
            self._drain_reason = drain_reason
            self._drain_event.set()
            callbacks = tuple(self._tool_cancel_callbacks.values())
        for callback in callbacks:
            try:
                callback()
            except Exception:
                continue

    @property
    def drain_requested(self) -> bool:
        return self._drain_event.is_set()

    @property
    def drain_reason(self) -> str | None:
        return self._drain_reason

    def wait(self, timeout: float | None = None) -> bool:
        return self._drain_event.wait(timeout)

    def register_tool_cancellation(self, callback: Callable[[], None]) -> Callable[[], None]:
        registration_id = uuid4().hex
        with self._tool_cancel_lock:
            cancel_now = self.drain_requested
            if not cancel_now:
                self._tool_cancel_callbacks[registration_id] = callback
        if cancel_now:
            callback()

        def unregister() -> None:
            with self._tool_cancel_lock:
                self._tool_cancel_callbacks.pop(registration_id, None)

        return unregister


class RuntimeRunControlRegistry:
    """Own exactly one cooperative control per active RuntimeInstance."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._controls: dict[str, RuntimeRunControl] = {}

    def register(self, runtime_instance_id: str) -> RuntimeRunControl:
        instance_id = _required_text(runtime_instance_id, "runtime_instance_id")
        control = RuntimeRunControl()
        with self._lock:
            if instance_id in self._controls:
                raise RuntimeError(f"runtime control is already registered: {instance_id}")
            self._controls[instance_id] = control
        return control

    def request_drain(self, *, runtime_instance_id: str | None, reason: str) -> int:
        instance_id = str(runtime_instance_id or "").strip()
        drain_reason = _required_text(reason, "reason")
        with self._lock:
            controls = (
                (self._controls[instance_id],)
                if instance_id and instance_id in self._controls
                else tuple(self._controls.values())
                if not instance_id
                else ()
            )
        for control in controls:
            control.request_drain(drain_reason)
        return len(controls)

    def release(self, runtime_instance_id: str, control: RuntimeRunControl) -> None:
        instance_id = _required_text(runtime_instance_id, "runtime_instance_id")
        with self._lock:
            if self._controls.get(instance_id) is control:
                self._controls.pop(instance_id, None)


def _required_text(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text
