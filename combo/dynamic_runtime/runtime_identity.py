from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from pathlib import Path
from types import MappingProxyType
from typing import Any

from combo.runtime_protocol import RuntimeExecutionIdentity, RuntimeInstance
from combo.tooling.workspace_paths import resolve_workspace_path


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
        browser_operation_timeout_ms=request.policy_snapshot.browser_operation_timeout_ms,
        browser_navigation_timeout_ms=request.policy_snapshot.browser_navigation_timeout_ms,
        locale=request.policy_snapshot.locale,
        timezone=request.policy_snapshot.timezone,
        context_compression_detail=request.policy_snapshot.context_compression_detail,
        context_compression_keep_recent_messages=(
            request.policy_snapshot.context_compression_keep_recent_messages
        ),
        memory_agent_write_enabled=request.policy_snapshot.memory_agent_write_enabled,
        memory_policy={
            "automatic_recall_enabled": request.policy_snapshot.memory_auto_recall_enabled,
            "max_items": request.policy_snapshot.memory_max_injected_items,
            "max_tokens": request.policy_snapshot.memory_max_injected_tokens,
        },
    )


class RuntimeScopedContextResources:
    """Expose immutable execution context only inside the claimed runtime scope."""

    def __init__(self, workspace_root_resolver: Callable[[str, str], str]) -> None:
        self._workspace_root_resolver = workspace_root_resolver
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

    def resolve_workspace_path(self, value: str) -> Path:
        identity = self._identity.get()
        if identity is None:
            raise RuntimeError("runtime execution context is not bound")
        root = self._workspace_root_resolver(identity.workspace_id, identity.principal_id)
        return resolve_workspace_path(value, root=Path(root))
