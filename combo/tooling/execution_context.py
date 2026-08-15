from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from dataclasses import dataclass
import threading
import time
from typing import Any, Callable, Iterator


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
_RUNTIME_RUN_CONTROL: ContextVar[Any | None] = ContextVar(
    "combo_runtime_run_control",
    default=None,
)
_TOOL_CANCELLATION_SCOPE: ContextVar["ToolCancellationScope | None"] = ContextVar(
    "combo_tool_cancellation_scope",
    default=None,
)


class RuntimeToolExecutionCancelled(RuntimeError):
    pass


class RuntimeToolExecutionTimedOut(TimeoutError):
    pass


class RuntimeModelGenerationInterrupted(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        partial_text: str = "",
        reasoning_content: str = "",
        partial_tool_calls: tuple[dict[str, Any], ...] = (),
    ) -> None:
        super().__init__(message)
        self.partial_text = str(partial_text or "")
        self.reasoning_content = str(reasoning_content or "")
        self.partial_tool_calls = tuple(
            dict(call)
            for call in (partial_tool_calls or ())
            if isinstance(call, dict)
        )


class ToolCancellationScope:
    """Own cancellation hooks for one tool invocation, including timeout cleanup."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._next_id = 0
        self._cancelled = False

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
def runtime_run_control_context(control: Any | None) -> Iterator[None]:
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


def current_runtime_run_control() -> Any | None:
    return _RUNTIME_RUN_CONTROL.get()


def runtime_terminal_cancellation_requested() -> bool:
    control = current_runtime_run_control()
    return bool(control is not None and getattr(control, "drain_requested", False))


def runtime_tool_interruption_requested() -> bool:
    control = current_runtime_run_control()
    return bool(control is not None and getattr(control, "tool_interrupt_requested", False))


def consume_runtime_inputs() -> tuple[Any, ...]:
    control = current_runtime_run_control()
    consume = getattr(control, "consume_inputs", None)
    if not callable(consume):
        return ()
    return tuple(consume())


def begin_runtime_model_generation() -> int:
    control = current_runtime_run_control()
    begin = getattr(control, "begin_model_generation", None)
    if callable(begin):
        try:
            return int(begin())
        except RuntimeError as exc:
            raise RuntimeModelGenerationInterrupted(str(exc)) from exc
    return 0


def runtime_model_generation_is_current(revision: int) -> bool:
    control = current_runtime_run_control()
    current = getattr(control, "generation_is_current", None)
    return bool(current(revision)) if callable(current) else True


def register_runtime_model_cancellation(callback: Callable[[], None]) -> Callable[[], None]:
    control = current_runtime_run_control()
    register = getattr(control, "register_model_cancellation", None)
    if callable(register):
        return register(callback)
    if control is not None and bool(getattr(control, "drain_requested", False)):
        callback()
    return lambda: None


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
    register = getattr(control, "register_tool_cancellation", None)
    if callable(register):
        unregister_runtime = register(callback)
        return lambda: (unregister_runtime(), unregister_local())
    if control is not None and bool(getattr(control, "drain_requested", False)):
        callback()
    return unregister_local


def execute_with_runtime_cancellation(
    operation: Callable[[], Any],
    *,
    timeout_seconds: float,
) -> Any:
    """Run a synchronous tool operation behind the shared run cancellation boundary.

    Python cannot safely terminate an arbitrary worker thread. On cancellation the
    graph is released immediately and the worker is detached; cancellable tools such
    as MCP and shell also register their own hook to terminate external I/O.
    """

    if timeout_seconds <= 0:
        raise ValueError("tool timeout_seconds must be positive")
    control = current_runtime_run_control()
    if control is not None and (
        bool(getattr(control, "drain_requested", False))
        or bool(getattr(control, "tool_interrupt_requested", False))
    ):
        raise RuntimeToolExecutionCancelled(_runtime_cancel_reason(control))

    completed = threading.Event()
    cancelled = threading.Event()
    outcome: dict[str, Any] = {}
    cancellation_scope = ToolCancellationScope()
    scope_token = _TOOL_CANCELLATION_SCOPE.set(cancellation_scope)
    context = copy_context()
    _TOOL_CANCELLATION_SCOPE.reset(scope_token)

    def run() -> None:
        try:
            outcome["value"] = context.run(operation)
        except BaseException as exc:
            outcome["error"] = exc
        finally:
            completed.set()

    unregister = register_runtime_tool_cancellation(cancelled.set)
    worker = threading.Thread(target=run, name="combo-tool-call", daemon=True)
    worker.start()
    deadline = time.monotonic() + timeout_seconds
    try:
        while not completed.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                cancellation_scope.cancel()
                raise RuntimeToolExecutionTimedOut(
                    f"Tool execution timed out after {timeout_seconds:g} seconds."
                )
            if cancelled.wait(timeout=min(0.05, remaining)) or (
                control is not None
                and (
                    bool(getattr(control, "drain_requested", False))
                    or bool(getattr(control, "tool_interrupt_requested", False))
                )
            ):
                raise RuntimeToolExecutionCancelled(_runtime_cancel_reason(control))
        if cancelled.is_set() or (
            control is not None
            and (
                bool(getattr(control, "drain_requested", False))
                or bool(getattr(control, "tool_interrupt_requested", False))
            )
        ):
            raise RuntimeToolExecutionCancelled(_runtime_cancel_reason(control))
        error = outcome.get("error")
        if error is not None:
            raise error
        return outcome.get("value")
    finally:
        unregister()
        clear_interrupt = getattr(control, "clear_tool_interrupt", None)
        if callable(clear_interrupt):
            clear_interrupt()


def _runtime_cancel_reason(control: Any) -> str:
    reason = str(
        getattr(control, "drain_reason", None)
        or getattr(control, "tool_interrupt_reason", None)
        or "user_cancelled"
    )
    return f"Tool execution cancelled: {reason}"
