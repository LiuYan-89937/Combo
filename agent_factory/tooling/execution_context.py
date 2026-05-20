from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable, Iterator


@dataclass(frozen=True, slots=True)
class CurrentToolCall:
    tool_id: str
    tool_call_id: str
    event_sink: Callable[[dict[str, Any]], None] | None = None


@dataclass(frozen=True, slots=True)
class ToolApprovalOverride:
    reason: str


_CURRENT_TOOL_CALL: ContextVar[CurrentToolCall | None] = ContextVar(
    "agentfactory_current_tool_call",
    default=None,
)
_TOOL_APPROVAL_OVERRIDE: ContextVar[ToolApprovalOverride | None] = ContextVar(
    "agentfactory_tool_approval_override",
    default=None,
)


@contextmanager
def tool_call_context(
    *,
    tool_id: str,
    tool_call_id: str,
    event_sink: Callable[[dict[str, Any]], None] | None = None,
) -> Iterator[None]:
    token = _CURRENT_TOOL_CALL.set(CurrentToolCall(tool_id=tool_id, tool_call_id=tool_call_id, event_sink=event_sink))
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


def current_tool_call() -> CurrentToolCall | None:
    return _CURRENT_TOOL_CALL.get()


def current_tool_event_sink() -> Callable[[dict[str, Any]], None] | None:
    current = current_tool_call()
    return current.event_sink if current is not None else None


def current_tool_approval_override() -> ToolApprovalOverride | None:
    return _TOOL_APPROVAL_OVERRIDE.get()
