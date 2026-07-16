from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Mapping


@dataclass(frozen=True, slots=True)
class CurrentToolCall:
    tool_id: str
    tool_call_id: str
    origin_node_id: str = ""
    origin_impl: str = ""
    event_sink: Callable[[dict[str, Any]], None] | None = None
    runtime_resource_overrides: Mapping[str, Any] | None = None


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
    origin_node_id: str = "",
    origin_impl: str = "",
    event_sink: Callable[[dict[str, Any]], None] | None = None,
    runtime_resource_overrides: Mapping[str, Any] | None = None,
) -> Iterator[None]:
    token = _CURRENT_TOOL_CALL.set(
        CurrentToolCall(
            tool_id=tool_id,
            tool_call_id=tool_call_id,
            origin_node_id=origin_node_id,
            origin_impl=origin_impl,
            event_sink=event_sink,
            runtime_resource_overrides=dict(runtime_resource_overrides or {}),
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


def current_tool_call() -> CurrentToolCall | None:
    return _CURRENT_TOOL_CALL.get()


def current_tool_event_sink() -> Callable[[dict[str, Any]], None] | None:
    current = current_tool_call()
    return current.event_sink if current is not None else None


def current_tool_runtime_resource_overrides() -> Mapping[str, Any]:
    current = current_tool_call()
    return current.runtime_resource_overrides if current is not None and current.runtime_resource_overrides else {}


def current_tool_approval_override() -> ToolApprovalOverride | None:
    return _TOOL_APPROVAL_OVERRIDE.get()
