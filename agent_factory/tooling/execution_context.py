from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True, slots=True)
class CurrentToolCall:
    tool_id: str
    tool_call_id: str


_CURRENT_TOOL_CALL: ContextVar[CurrentToolCall | None] = ContextVar(
    "agentfactory_current_tool_call",
    default=None,
)


@contextmanager
def tool_call_context(*, tool_id: str, tool_call_id: str) -> Iterator[None]:
    token = _CURRENT_TOOL_CALL.set(CurrentToolCall(tool_id=tool_id, tool_call_id=tool_call_id))
    try:
        yield
    finally:
        _CURRENT_TOOL_CALL.reset(token)


def current_tool_call() -> CurrentToolCall | None:
    return _CURRENT_TOOL_CALL.get()
