from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator

from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext


_CURRENT_CONTEXT: ContextVar[NodeExecutionContext | None] = ContextVar(
    "factory_package_node_context",
    default=None,
)


@contextmanager
def factory_package_node_context(context: NodeExecutionContext) -> Iterator[None]:
    token = _CURRENT_CONTEXT.set(context)
    try:
        yield
    finally:
        _CURRENT_CONTEXT.reset(token)


def current_factory_package_context() -> NodeExecutionContext | None:
    return _CURRENT_CONTEXT.get()
