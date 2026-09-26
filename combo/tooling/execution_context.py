from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from dataclasses import dataclass
import threading
import time
from typing import Any, Callable, Iterator, Protocol

from combo.runtime_protocol.interruption import (
    RuntimeModelGenerationInterrupted,
    RuntimeToolExecutionCancelled,
    RuntimeToolExecutionTimedOut,
)


@dataclass(frozen=True, slots=True)
class CurrentToolCall:
    tool_id: str
    tool_call_id: str
    origin_node_id: str = ""
    origin_impl: str = ""
    event_sink: Callable[[dict[str, Any]], None] | None = None


@dataclass(frozen=True, slots=True)
class ToolApprovalOverride:
    reason: str


class RuntimeRunControlPort(Protocol):
    @property
    def drain_requested(self) -> bool: ...

    @property
    def drain_reason(self) -> str | None: ...

    @property
    def tool_interrupt_requested(self) -> bool: ...

    @property
    def tool_interrupt_reason(self) -> str | None: ...

    def consume_inputs(self) -> tuple[Any, ...]: ...
    def acknowledge_checkpointed_inputs(self, messages: list[Any]) -> tuple[str, ...]: ...
    def begin_model_generation(self) -> int: ...
    def generation_is_current(self, revision: int) -> bool: ...
    def register_model_cancellation(self, callback: Callable[[], None]) -> Callable[[], None]: ...
    def register_tool_cancellation(self, callback: Callable[[], None]) -> Callable[[], None]: ...
    def clear_tool_interrupt(self) -> None: ...


_CURRENT_TOOL_CALL: ContextVar[CurrentToolCall | None] = ContextVar(
    "combo_current_tool_call",
    default=None,
)
_TOOL_APPROVAL_OVERRIDE: ContextVar[ToolApprovalOverride | None] = ContextVar(
    "combo_tool_approval_override",
    default=None,
)
_TOOL_OUTPUT_SESSION_ID: ContextVar[str | None] = ContextVar(
    "combo_tool_output_session_id",
    default=None,
)
_RUNTIME_RUN_CONTROL: ContextVar[RuntimeRunControlPort | None] = ContextVar(
    "combo_runtime_run_control",
    default=None,
)
_TOOL_CANCELLATION_SCOPE: ContextVar["ToolCancellationScope | None"] = ContextVar(
    "combo_tool_cancellation_scope",
    default=None,
)


class ToolCancellationScope:
    """Own cancellation hooks for one tool invocation, including timeout cleanup."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._next_id = 0
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def register(self, callback: Callable[[], None]) -> Callable[[], None]:
        with self._lock:
            self._next_id += 1
            registration_id = self._next_id
            cancel_now = self._cancelled
            if not cancel_now:
                self._callbacks[registration_id] = callback
        if cancel_now:
            callback()

        def unregister() -> None:
            with self._lock:
                self._callbacks.pop(registration_id, None)

        return unregister

    def cancel(self) -> None:
        with self._lock:
            if self._cancelled:
                return
            self._cancelled = True
            callbacks = tuple(self._callbacks.values())
        for callback in callbacks:
            try:
                callback()
            except Exception:
                continue


@contextmanager
def tool_call_context(
    *,
    tool_id: str,
    tool_call_id: str,
    origin_node_id: str = "",
    origin_impl: str = "",
    event_sink: Callable[[dict[str, Any]], None] | None = None,
) -> Iterator[None]:
    token = _CURRENT_TOOL_CALL.set(
        CurrentToolCall(
            tool_id=tool_id,
            tool_call_id=tool_call_id,
            origin_node_id=origin_node_id,
            origin_impl=origin_impl,
            event_sink=event_sink,
        )
    )
    try:
        yield
    finally:
        _CURRENT_TOOL_CALL.reset(token)


@contextmanager
def tool_approval_override(*, reason: str) -> Iterator[None]:
    token = _TOOL_APPROVAL_OVERRIDE.set(ToolApprovalOverride(reason=reason))
    try:
        yield
    finally:
        _TOOL_APPROVAL_OVERRIDE.reset(token)


@contextmanager
def tool_output_session_context(session_id: str) -> Iterator[None]:
    normalized = str(session_id or "").strip()
    if not normalized:
        raise ValueError("tool output session id is required")
    if normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
        raise ValueError("tool output session id must be a path-safe identifier")
    token = _TOOL_OUTPUT_SESSION_ID.set(normalized)
    try:
        yield
    finally:
        _TOOL_OUTPUT_SESSION_ID.reset(token)


@contextmanager
def runtime_run_control_context(control: RuntimeRunControlPort | None) -> Iterator[None]:
    token = _RUNTIME_RUN_CONTROL.set(control)
    try:
        yield
    finally:
        _RUNTIME_RUN_CONTROL.reset(token)


def current_tool_call() -> CurrentToolCall | None:
    return _CURRENT_TOOL_CALL.get()


def current_tool_event_sink() -> Callable[[dict[str, Any]], None] | None:
    current = current_tool_call()
    return current.event_sink if current is not None else None


def current_tool_approval_override() -> ToolApprovalOverride | None:
    return _TOOL_APPROVAL_OVERRIDE.get()


def current_tool_output_session_id() -> str | None:
    return _TOOL_OUTPUT_SESSION_ID.get()


def current_runtime_run_control() -> RuntimeRunControlPort | None:
    return _RUNTIME_RUN_CONTROL.get()


def runtime_terminal_cancellation_requested() -> bool:
    control = current_runtime_run_control()
    return control.drain_requested if control is not None else False


def runtime_tool_interruption_requested() -> bool:
    control = current_runtime_run_control()
    return control.tool_interrupt_requested if control is not None else False


def runtime_tool_cancellation_requested() -> bool:
    scope = _TOOL_CANCELLATION_SCOPE.get()
    return (scope is not None and scope.cancelled) or runtime_terminal_cancellation_requested() or runtime_tool_interruption_requested()


def consume_runtime_inputs() -> tuple[Any, ...]:
    control = current_runtime_run_control()
    return control.consume_inputs() if control is not None else ()


def acknowledge_runtime_inputs(messages: list[Any]) -> None:
    control = current_runtime_run_control()
    if control is not None:
        control.acknowledge_checkpointed_inputs(messages)


def begin_runtime_model_generation() -> int:
    control = current_runtime_run_control()
    if control is not None:
        try:
            return control.begin_model_generation()
        except RuntimeError as exc:
            raise RuntimeModelGenerationInterrupted(str(exc)) from exc
    return 0


def runtime_model_generation_is_current(revision: int) -> bool:
    control = current_runtime_run_control()
    return control.generation_is_current(revision) if control is not None else True


def register_runtime_model_cancellation(callback: Callable[[], None]) -> Callable[[], None]:
    control = current_runtime_run_control()
    return control.register_model_cancellation(callback) if control is not None else lambda: None


def execute_runtime_model_invocation(operation: Callable[[], Any], *, revision: int) -> Any:
    """Make a non-streaming provider call interruptible without making interruption terminal."""
    control = current_runtime_run_control()
    if control is None:
        return operation()
    completed = threading.Event()
    cancelled = threading.Event()
    outcome: dict[str, Any] = {}
    context = copy_context()

    def run() -> None:
        try:
            outcome["value"] = context.run(operation)
        except BaseException as exc:
            outcome["error"] = exc
        finally:
            completed.set()

    unregister = register_runtime_model_cancellation(cancelled.set)
    worker = threading.Thread(target=run, name="combo-model-call", daemon=True)
    worker.start()
    try:
        while not completed.is_set():
            if cancelled.wait(timeout=0.05) or not runtime_model_generation_is_current(revision):
                raise RuntimeModelGenerationInterrupted("Model generation was superseded.")
        if cancelled.is_set() or not runtime_model_generation_is_current(revision):
            raise RuntimeModelGenerationInterrupted("Model generation was superseded.")
        error = outcome.get("error")
        if error is not None:
            raise error
        return outcome.get("value")
    finally:
        unregister()


def register_runtime_tool_cancellation(callback: Callable[[], None]) -> Callable[[], None]:
    local_scope = _TOOL_CANCELLATION_SCOPE.get()
    unregister_local = local_scope.register(callback) if local_scope is not None else lambda: None
    control = current_runtime_run_control()
    if control is not None:
        unregister_runtime = control.register_tool_cancellation(callback)

        def unregister() -> None:
            unregister_runtime()
            unregister_local()

        return unregister
    return unregister_local


def execute_with_runtime_cancellation(
    operation: Callable[[], Any],
    *,
    timeout_seconds: float | None,
    cancellation_event: threading.Event | None = None,
) -> Any:
    """Run a synchronous tool operation behind the shared run cancellation boundary.

    Python cannot safely terminate an arbitrary worker thread. On cancellation the
    graph is released immediately and the worker is detached; cancellable tools such
    as MCP and shell also register their own hook to terminate external I/O.
    """

    if timeout_seconds is not None and timeout_seconds <= 0:
        raise ValueError("tool timeout_seconds must be positive")
    control = current_runtime_run_control()
    if control is not None and (
        control.drain_requested
        or control.tool_interrupt_requested
    ):
        raise RuntimeToolExecutionCancelled(_runtime_cancel_reason(control))

    if cancellation_event is not None and cancellation_event.is_set():
        raise RuntimeToolExecutionCancelled(_runtime_cancel_reason(control))

    completed = threading.Event()
    cancelled = cancellation_event if cancellation_event is not None else threading.Event()
    outcome: dict[str, Any] = {}
    cancellation_scope = ToolCancellationScope()
    scope_token = _TOOL_CANCELLATION_SCOPE.set(cancellation_scope)
    context = copy_context()
    _TOOL_CANCELLATION_SCOPE.reset(scope_token)

    def run() -> None:
        try:
            if cancelled.is_set():
                return
            outcome["value"] = context.run(operation)
        except BaseException as exc:
            outcome["error"] = exc
        finally:
            completed.set()

    unregister = register_runtime_tool_cancellation(cancelled.set)
    worker = threading.Thread(target=run, name="combo-tool-call", daemon=True)
    worker.start()
    deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None
    try:
        while not completed.is_set():
            remaining = deadline - time.monotonic() if deadline is not None else None
            if remaining is not None and remaining <= 0:
                cancellation_scope.cancel()
                raise RuntimeToolExecutionTimedOut(
                    f"Tool execution timed out after {timeout_seconds:g} seconds."
                )
            if cancelled.wait(timeout=min(0.05, remaining) if remaining is not None else 0.05) or (
                control is not None
                and (
                    control.drain_requested
                    or control.tool_interrupt_requested
                )
            ):
                raise RuntimeToolExecutionCancelled(_runtime_cancel_reason(control))
        if cancelled.is_set() or (
            control is not None
            and (
                control.drain_requested
                or control.tool_interrupt_requested
            )
        ):
            raise RuntimeToolExecutionCancelled(_runtime_cancel_reason(control))
        error = outcome.get("error")
        if error is not None:
            raise error
        return outcome.get("value")
    finally:
        unregister()
        if control is not None:
            control.clear_tool_interrupt()


def _runtime_cancel_reason(control: RuntimeRunControlPort | None) -> str:
    reason = (control.drain_reason or control.tool_interrupt_reason) if control is not None else None
    return f"Tool execution cancelled: {reason or 'user_cancelled'}"
