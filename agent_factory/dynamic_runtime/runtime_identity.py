from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from types import MappingProxyType
from typing import Any

from agent_factory.runtime_protocol import RuntimeExecutionIdentity, RuntimeInstance


def runtime_execution_identity(instance: RuntimeInstance) -> RuntimeExecutionIdentity:
    if instance.attempt_id is None:
        raise RuntimeError("runtime execution identity requires a claimed attempt")
    request = instance.request
    return RuntimeExecutionIdentity(
        principal_id=request.principal_id,
        request_id=request.request_id,
        runtime_instance_id=instance.runtime_instance_id,
        attempt_id=instance.attempt_id,
        session_id=request.session_id,
        turn_id=request.turn_id,
        workspace_id=request.workspace_id,
        runtime_role=request.runtime_role,
        parent_runtime_instance_id=request.parent_runtime_instance_id,
        task_id=request.task_id,
        delegation_grant_id=request.delegation_grant_id,
        scheduler_run_id=request.scheduler_run_id,
        task_revision=request.task_revision,
        generation=instance.generation,
        memory_agent_write_enabled=request.policy_snapshot.memory_agent_write_enabled,
        memory_policy={
            "max_items": request.policy_snapshot.memory_max_injected_items,
            "max_tokens": request.policy_snapshot.memory_max_injected_tokens,
        },
    )


class RuntimeScopedContextResources:
    """Expose immutable execution context only inside the claimed runtime scope."""

    def __init__(self) -> None:
        self._identity: ContextVar[RuntimeExecutionIdentity | None] = ContextVar(
            "dynamic_runtime_execution_identity",
            default=None,
        )

    @contextmanager
    def bind(self, instance: RuntimeInstance) -> Iterator[None]:
        identity = runtime_execution_identity(instance)
        current = self._identity.get()
        if current is not None and current != identity:
            raise RuntimeError("runtime context already carries a different execution identity")
        token: Token[RuntimeExecutionIdentity | None] = self._identity.set(identity)
        try:
            yield
        finally:
            self._identity.reset(token)

    def current(self) -> Mapping[str, Any]:
        identity = self._identity.get()
        if identity is None:
            raise RuntimeError("runtime execution context is not bound")
        return MappingProxyType({"runtime_identity": identity})
