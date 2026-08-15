from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class RuntimeInputInjection:
    injection_id: str
    role: Literal["user", "system"]
    content: str

    def __post_init__(self) -> None:
        _required_text(self.injection_id, "injection_id")
        _required_text(self.content, "content")


class RuntimeRunControl:
    """Own terminal cancellation, model-generation interruption, and steering input delivery."""

    __slots__ = (
        "_drain_event",
        "_drain_reason",
        "_tool_interrupt_event",
        "_tool_interrupt_reason",
        "_tool_cancel_callbacks",
        "_tool_cancel_lock",
        "_input_injections",
        "_claimed_input_injections",
        "_input_checkpoint_callbacks",
        "_model_cancel_callbacks",
        "_generation_revision",
    )

    def __init__(self) -> None:
        self._drain_event = threading.Event()
        self._drain_reason: str | None = None
        self._tool_interrupt_event = threading.Event()
        self._tool_interrupt_reason: str | None = None
        self._tool_cancel_lock = threading.RLock()
        self._tool_cancel_callbacks: dict[str, Callable[[], None]] = {}
        self._input_injections: dict[str, RuntimeInputInjection] = {}
        self._claimed_input_injections: dict[str, RuntimeInputInjection] = {}
        self._input_checkpoint_callbacks: dict[str, Callable[[], None]] = {}
        self._model_cancel_callbacks: dict[str, Callable[[], None]] = {}
        self._generation_revision = 0

    def request_drain(self, reason: str = "shutdown") -> None:
        drain_reason = _required_text(reason, "reason")
        with self._tool_cancel_lock:
            if self._drain_event.is_set():
                return
            self._drain_reason = drain_reason
            self._drain_event.set()
            callbacks = (
                *self._model_cancel_callbacks.values(),
                *self._tool_cancel_callbacks.values(),
            )
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

    def begin_model_generation(self) -> int:
        with self._tool_cancel_lock:
            if self._drain_event.is_set():
                raise RuntimeError(self._drain_reason or "runtime cancellation requested")
            return self._generation_revision

    def request_generation_interrupt(self) -> int:
        """Invalidate only the active model generation; tools and the Runtime remain alive."""
        with self._tool_cancel_lock:
            if self._drain_event.is_set():
                return self._generation_revision
            self._generation_revision += 1
            callbacks = tuple(self._model_cancel_callbacks.values())
            revision = self._generation_revision
        for callback in callbacks:
            try:
                callback()
            except Exception:
                continue
        return revision

    def request_tool_interrupt(self, reason: str = "user_steered") -> bool:
        """Cancel the active tool without making the whole runtime terminal.

        Steering can arrive while a tool is blocking the graph.  A drain would
        incorrectly cancel the conversation itself, so tool interruption has a
        separate cooperative boundary.  Registered tool callbacks still get
        invoked immediately (MCP/browser/process/package workers use these
        callbacks to release their external operation).
        """
        interrupt_reason = _required_text(reason, "reason")
        with self._tool_cancel_lock:
            if not self._tool_cancel_callbacks:
                return False
            self._tool_interrupt_reason = interrupt_reason
            self._tool_interrupt_event.set()
            callbacks = tuple(self._tool_cancel_callbacks.values())
        for callback in callbacks:
            try:
                callback()
            except Exception:
                continue
        return True

    @property
    def tool_interrupt_requested(self) -> bool:
        return self._tool_interrupt_event.is_set()

    @property
    def tool_interrupt_reason(self) -> str | None:
        return self._tool_interrupt_reason

    def clear_tool_interrupt(self) -> None:
        with self._tool_cancel_lock:
            self._tool_interrupt_event.clear()
            self._tool_interrupt_reason = None

    def generation_is_current(self, revision: int) -> bool:
        with self._tool_cancel_lock:
            return not self._drain_event.is_set() and revision == self._generation_revision

    def register_model_cancellation(self, callback: Callable[[], None]) -> Callable[[], None]:
        registration_id = uuid4().hex
        with self._tool_cancel_lock:
            cancel_now = self._drain_event.is_set()
            if not cancel_now:
                self._model_cancel_callbacks[registration_id] = callback
        if cancel_now:
            callback()

        def unregister() -> None:
            with self._tool_cancel_lock:
                self._model_cancel_callbacks.pop(registration_id, None)

        return unregister

    def submit_input(
        self,
        injection: RuntimeInputInjection,
        *,
        on_checkpointed: Callable[[], None] | None = None,
    ) -> bool:
        with self._tool_cancel_lock:
            if self._drain_event.is_set():
                return False
            self._input_injections[injection.injection_id] = injection
            if on_checkpointed is not None:
                self._input_checkpoint_callbacks[injection.injection_id] = on_checkpointed
            return True

    def revoke_input(self, injection_id: str) -> None:
        with self._tool_cancel_lock:
            self._input_injections.pop(_required_text(injection_id, "injection_id"), None)
            self._claimed_input_injections.pop(injection_id, None)
            self._input_checkpoint_callbacks.pop(injection_id, None)

    def consume_inputs(self) -> tuple[RuntimeInputInjection, ...]:
        with self._tool_cancel_lock:
            inputs = tuple(self._input_injections.values())
            self._input_injections.clear()
            self._claimed_input_injections.update(
                (injection.injection_id, injection) for injection in inputs
            )
        return inputs

    def acknowledge_checkpointed_inputs(self, messages: list[Any]) -> tuple[str, ...]:
        message_ids = {
            str(getattr(message, "id", "") or "").strip()
            for message in messages
        }
        message_ids.discard("")
        with self._tool_cancel_lock:
            acknowledged = tuple(
                injection_id
                for injection_id in self._claimed_input_injections
                if injection_id in message_ids
            )
            callbacks = tuple(
                (injection_id, self._input_checkpoint_callbacks.get(injection_id))
                for injection_id in acknowledged
            )
        for injection_id, callback in callbacks:
            if callback is not None:
                callback()
            with self._tool_cancel_lock:
                self._claimed_input_injections.pop(injection_id, None)
                self._input_checkpoint_callbacks.pop(injection_id, None)
        return acknowledged

    def restore_uncheckpointed_inputs(self) -> None:
        with self._tool_cancel_lock:
            for injection_id, injection in self._claimed_input_injections.items():
                self._input_injections.setdefault(injection_id, injection)
            self._claimed_input_injections.clear()


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

    def submit_input(
        self,
        *,
        runtime_instance_id: str,
        injection: RuntimeInputInjection,
        on_checkpointed: Callable[[], None] | None = None,
    ) -> bool:
        instance_id = _required_text(runtime_instance_id, "runtime_instance_id")
        with self._lock:
            control = self._controls.get(instance_id)
        return (
            control.submit_input(injection, on_checkpointed=on_checkpointed)
            if control is not None
            else False
        )

    def request_generation_interrupt(self, *, runtime_instance_id: str) -> bool:
        instance_id = _required_text(runtime_instance_id, "runtime_instance_id")
        with self._lock:
            control = self._controls.get(instance_id)
        if control is None:
            return False
        control.request_generation_interrupt()
        return True

    def request_tool_interrupt(self, *, runtime_instance_id: str, reason: str = "user_steered") -> bool:
        instance_id = _required_text(runtime_instance_id, "runtime_instance_id")
        with self._lock:
            control = self._controls.get(instance_id)
        if control is None:
            return False
        return control.request_tool_interrupt(reason)

    def revoke_input(self, *, runtime_instance_id: str, injection_id: str) -> None:
        instance_id = _required_text(runtime_instance_id, "runtime_instance_id")
        with self._lock:
            control = self._controls.get(instance_id)
        if control is not None:
            control.revoke_input(injection_id)

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
