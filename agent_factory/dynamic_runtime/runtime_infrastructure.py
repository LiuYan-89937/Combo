from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import importlib
from pathlib import Path
from threading import RLock
from types import MappingProxyType
from typing import Any

from agent_factory.dynamic_runtime.capability_definitions import (
    MCPServerDefinition,
    MCPToolDefinition,
    ToolDefinition,
)
from agent_factory.dynamic_runtime.mcp_runtime import MCPRuntimePool
from agent_factory.dynamic_runtime.capability_catalog_runtime import CapabilityCatalogRuntime
from agent_factory.dynamic_runtime.memory_store import ScopedMemoryStore
from agent_factory.dynamic_runtime.delegation_store import DelegationStore
from agent_factory.dynamic_runtime.delegation_runtime import DelegationRuntimeCoordinator
from agent_factory.dynamic_runtime.runtime_identity import runtime_execution_identity
from agent_factory.dynamic_runtime.repositories import ConversationStore
from agent_factory.dynamic_runtime.snapshot_tool_execution import (
    SnapshotMCPEntrypointResolver,
    SnapshotToolEntrypointResolver,
    SnapshotToolOutputResolver,
    SnapshotToolResourceResolver,
    ToolEntrypointLease,
    ToolOutputRuntimeLease,
    ToolResourceLease,
)
from agent_factory.dynamic_runtime.launch_context import (
    AttachmentLaunchResolver,
    WorkspaceLaunchProjection,
    WorkspaceLaunchResolver,
)
from agent_factory.resource_system import ResourceDescriptor, ResourceIdentity, ResourceStore
from agent_factory.runtime_protocol import (
    AttachmentRevisionRef,
    CapabilityProjectionSnapshot,
    CapabilitySnapshot,
    RuntimeInstance,
)
from agent_factory.tooling.output_store import ToolOutputStore
from agent_factory.tooling.builtins.browser.runtime import BrowserRuntime
from agent_factory.tooling.builtins.process.manager import ProcessManager, ProcessRuntimeResource
from agent_factory.tooling.builtins.process.runtime import resolve_shell_runtime
from agent_factory.tooling.builtins.filesystem.common import FilesystemRuntimeResource
from agent_factory.tooling.builtins.filesystem.file_locks import WorkspaceFileLockManager
from agent_factory.tooling.builtins.filesystem.staged_write import StagedWriteStore
from agent_factory.tooling.builtins.filesystem.workspace_transaction import WorkspaceTransactionStore


ReleaseCallback = Callable[[], None]


def release_borrowed_runtime_resource() -> None:
    return None


@dataclass(frozen=True, slots=True)
class ProjectedRuntimeResource:
    value: Any
    release_callback: ReleaseCallback = release_borrowed_runtime_resource

    def __post_init__(self) -> None:
        if not callable(self.release_callback):
            raise TypeError("projected runtime resource requires a release callback")


RuntimeResourceFactory = Callable[[RuntimeInstance], ProjectedRuntimeResource]


@dataclass(slots=True)
class _ProcessPoolEntry:
    resource: ProcessRuntimeResource
    references: int


class RuntimeProcessResourcePool:
    """Own one isolated process manager per runtime attempt and fence its handles."""

    def __init__(self, *, environment: Mapping[str, str]) -> None:
        self._environment = MappingProxyType(dict(environment))
        self._shell_runtime = resolve_shell_runtime(self._environment)
        self._entries: dict[str, _ProcessPoolEntry] = {}
        self._lock = RLock()

    def acquire(
        self,
        instance: RuntimeInstance,
        *,
        root: Path,
        allowed_write_paths: tuple[Path, ...] = (),
        write_scope_enforced: bool = False,
    ) -> ProjectedRuntimeResource:
        key = _runtime_attempt_key(instance)
        resolved_root = root.expanduser().resolve()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                entry = _ProcessPoolEntry(
                    resource=ProcessRuntimeResource(
                        manager=ProcessManager(
                            environment=self._environment,
                            shell_runtime=self._shell_runtime,
                        ),
                        root=resolved_root,
                    ),
                    references=0,
                )
                self._entries[key] = entry
            elif entry.resource.root != resolved_root:
                raise RuntimeError("runtime attempt process root changed while leased")
            entry.references += 1
        return ProjectedRuntimeResource(value=entry.resource, release_callback=lambda: self._release(key))

    def close(self) -> None:
        with self._lock:
            entries = tuple(self._entries.values())
            self._entries.clear()
        for entry in entries:
            entry.resource.manager.close()

    def _release(self, key: str) -> None:
        resource: ProcessRuntimeResource | None = None
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            entry.references -= 1
            if entry.references < 0:
                raise RuntimeError("process runtime resource reference count underflow")
            if entry.references == 0:
                resource = self._entries.pop(key).resource
        if resource is not None:
            resource.manager.close()


@dataclass(slots=True)
class _FilesystemPoolEntry:
    resource: FilesystemRuntimeResource
    references: int


class RuntimeFilesystemResourcePool:
    """Own attempt-scoped filesystem transaction state and staging cleanup."""

    def __init__(self, *, staged_write_ttl_seconds: int, transaction_ttl_seconds: int) -> None:
        if staged_write_ttl_seconds < 60 or transaction_ttl_seconds < 60:
            raise ValueError("filesystem runtime TTLs must be at least 60 seconds")
        self._staged_write_ttl_seconds = staged_write_ttl_seconds
        self._transaction_ttl_seconds = transaction_ttl_seconds
        self._file_locks = WorkspaceFileLockManager()
        self._entries: dict[str, _FilesystemPoolEntry] = {}
        self._lock = RLock()

    def acquire(
        self,
        instance: RuntimeInstance,
        *,
        root: Path,
        allowed_write_paths: tuple[Path, ...] = (),
        write_scope_enforced: bool = False,
    ) -> ProjectedRuntimeResource:
        key = _runtime_attempt_key(instance)
        resolved_root = root.expanduser().resolve()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                entry = _FilesystemPoolEntry(
                    resource=FilesystemRuntimeResource(
                        root=resolved_root,
                        staged_write_store=StagedWriteStore(
                            ttl_seconds=self._staged_write_ttl_seconds
                        ),
                        transaction_store=WorkspaceTransactionStore(
                            ttl_seconds=self._transaction_ttl_seconds
                        ),
                        file_locks=self._file_locks,
                        allowed_write_paths=allowed_write_paths,
                        write_scope_enforced=write_scope_enforced,
                    ),
                    references=0,
                )
                self._entries[key] = entry
            elif entry.resource.root != resolved_root:
                raise RuntimeError("runtime attempt filesystem root changed while leased")
            elif (
                entry.resource.allowed_write_paths != allowed_write_paths
                or entry.resource.write_scope_enforced != write_scope_enforced
            ):
                raise RuntimeError("runtime attempt filesystem write scope changed while leased")
            entry.references += 1
        return ProjectedRuntimeResource(value=entry.resource, release_callback=lambda: self._release(key))

    def close(self) -> None:
        with self._lock:
            entries = tuple(self._entries.values())
            self._entries.clear()
        for entry in entries:
            entry.resource.staged_write_store.close()

    def _release(self, key: str) -> None:
        resource: FilesystemRuntimeResource | None = None
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            entry.references -= 1
            if entry.references < 0:
                raise RuntimeError("filesystem runtime resource reference count underflow")
            if entry.references == 0:
                resource = self._entries.pop(key).resource
        if resource is not None:
            resource.staged_write_store.close()


class PythonModuleToolEntrypointResolver(SnapshotToolEntrypointResolver):
    """Resolve a published Python module target only when its runtime lease begins."""

    def acquire(
        self,
        *,
        definition: ToolDefinition,
        projection: CapabilityProjectionSnapshot,
        capability_snapshot: CapabilitySnapshot,
        runtime_instance: RuntimeInstance,
    ) -> ToolEntrypointLease:
        if definition.implementation.kind != "python_module":
            raise RuntimeError(
                f"tool implementation kind requires an isolated runtime adapter: {definition.implementation.kind}"
            )
        module_name, function_name = _module_target(definition.implementation.entrypoint)
        function = getattr(importlib.import_module(module_name), function_name, None)
        if not callable(function):
            raise RuntimeError(f"tool entrypoint is not callable: {definition.implementation.entrypoint}")
        risk_evaluator = None
        risk_target = definition.implementation.hard_risk_evaluator_entrypoint
        if risk_target is not None:
            risk_module_name, risk_function_name = _module_target(risk_target)
            risk_evaluator = getattr(importlib.import_module(risk_module_name), risk_function_name, None)
            if not callable(risk_evaluator):
                raise RuntimeError(f"tool risk evaluator is not callable: {risk_target}")
        return ToolEntrypointLease(
            entrypoint=function,
            hard_risk_evaluator=risk_evaluator,
            release_callback=release_borrowed_runtime_resource,
        )


class RevisionBoundMCPEntrypointResolver(SnapshotMCPEntrypointResolver):
    """Bind every projected MCP tool to its frozen server revision."""

    def __init__(self, runtime: MCPRuntimePool) -> None:
        self._runtime = runtime

    def acquire(
        self,
        *,
        definition: MCPToolDefinition,
        projection: CapabilityProjectionSnapshot,
        capability_snapshot: CapabilitySnapshot,
        runtime_instance: RuntimeInstance,
    ) -> ToolEntrypointLease:
        servers = tuple(
            item
            for item in capability_snapshot.projections
            if item.kind == "mcp_server" and item.capability_id == definition.server_capability_id
        )
        if len(servers) != 1:
            raise RuntimeError(
                f"MCP tool requires one frozen server projection: {definition.server_capability_id}"
            )
        server = servers[0]
        if server.runtime_definition_schema != "mcp_server_definition.v1":
            raise RuntimeError("MCP server projection uses an unsupported definition schema")
        MCPServerDefinition.model_validate(server.runtime_definition)

        def invoke(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
            if resources:
                raise RuntimeError("MCP entrypoint received unexpected runtime resources")
            return self._runtime.call_tool(
                server.content_digest,
                definition.upstream_tool_name,
                arguments,
            )

        return ToolEntrypointLease(
            entrypoint=invoke,
            hard_risk_evaluator=None,
            release_callback=release_borrowed_runtime_resource,
        )


class SnapshotRuntimeResourceProjector(SnapshotToolResourceResolver):
    def __init__(
        self,
        *,
        resource_store: ResourceStore,
        runtime_resource_factories: Mapping[str, RuntimeResourceFactory],
    ) -> None:
        self._resource_store = resource_store
        self._factories = MappingProxyType(dict(runtime_resource_factories))

    def acquire(
        self,
        *,
        definition: ToolDefinition,
        projection: CapabilityProjectionSnapshot,
        capability_snapshot: CapabilitySnapshot,
        runtime_instance: RuntimeInstance,
    ) -> ToolResourceLease:
        resources: dict[str, Any] = {}
        release_callbacks: list[ReleaseCallback] = []
        for name in definition.runtime_resources:
            factory = self._factories.get(name)
            if factory is None:
                raise RuntimeError(f"runtime resource projector is unavailable: {name}")
            projected = factory(runtime_instance)
            resources[name] = projected.value
            release_callbacks.append(projected.release_callback)
        try:
            for binding in definition.resource_bindings:
                descriptor = ResourceDescriptor(
                    identity=ResourceIdentity(
                        owner_kind="tool",
                        owner_id=projection.capability_id,
                        owner_revision=projection.revision,
                        resource_id=binding.resource_id,
                        resource_revision=binding.resource_revision,
                    ),
                    purpose=binding.purpose,
                )
                resources[binding.name] = self._resource_store.resolve(descriptor)
        except BaseException:
            _release_callbacks(release_callbacks)
            raise
        return ToolResourceLease(
            resources=resources,
            release_callback=lambda: _release_callbacks(release_callbacks),
        )


class SharedToolOutputResolver(SnapshotToolOutputResolver):
    def __init__(self, root: str | Path) -> None:
        self._store = ToolOutputStore(root)

    def acquire(
        self,
        *,
        projection: CapabilityProjectionSnapshot,
        capability_snapshot: CapabilitySnapshot,
        runtime_instance: RuntimeInstance,
        retain_raw_output: bool,
    ) -> ToolOutputRuntimeLease:
        return ToolOutputRuntimeLease(
            store=self._store if retain_raw_output else None,
            compression_model_resolver=None,
            release_callback=release_borrowed_runtime_resource,
        )


class ConversationWorkspaceLaunchResolver(WorkspaceLaunchResolver):
    def __init__(self, conversations: ConversationStore) -> None:
        self._conversations = conversations

    def resolve(self, *, principal_id: str, workspace_id: str) -> WorkspaceLaunchProjection:
        workspace = self._conversations.require_workspace(workspace_id)
        if workspace.principal_id != principal_id or workspace.status != "active":
            raise PermissionError("workspace is unavailable to the runtime principal")
        if workspace.kind != "managed" or workspace.managed_path is None:
            raise RuntimeError("mounted workspace resolution requires a platform mount adapter")
        return WorkspaceLaunchProjection(
            workspace_id=workspace.workspace_id,
            root_alias="workspace",
            root_path=workspace.managed_path,
            allow_external_paths=False,
        )


class UnavailableAttachmentLaunchResolver(AttachmentLaunchResolver):
    def resolve(self, *, principal_id: str, reference: AttachmentRevisionRef) -> dict[str, Any]:
        raise RuntimeError(
            f"attachment revision has no content-store adapter: {reference.attachment_id}@{reference.revision}"
        )


def runtime_resource_factory(
    conversations: ConversationStore,
    resource_name: str,
    *,
    browser_runtime: BrowserRuntime,
    capability_catalog: CapabilityCatalogRuntime,
    memory_store: ScopedMemoryStore,
    delegations: DelegationStore,
    delegation_runtime: DelegationRuntimeCoordinator,
    process_resources: RuntimeProcessResourcePool,
    filesystem_resources: RuntimeFilesystemResourcePool,
) -> RuntimeResourceFactory:
    if resource_name not in {
        "filesystem",
        "process_runtime",
        "runtime_identity",
        "browser_runtime",
        "capability_catalog",
        "memory_store",
        "delegation_runtime",
    }:
        raise ValueError(f"unsupported runtime resource: {resource_name}")

    def project(instance: RuntimeInstance) -> ProjectedRuntimeResource:
        if resource_name == "browser_runtime":
            session_key = _browser_session_key(instance)
            return ProjectedRuntimeResource(
                value=browser_runtime,
                release_callback=lambda: browser_runtime.close(
                    session_key=session_key,
                    page_id=None,
                    close_context=True,
                ),
            )
        if resource_name == "capability_catalog":
            return ProjectedRuntimeResource(value=capability_catalog)
        if resource_name == "memory_store":
            return ProjectedRuntimeResource(value=memory_store)
        if resource_name == "runtime_identity":
            return ProjectedRuntimeResource(value=runtime_execution_identity(instance))
        if resource_name == "delegation_runtime":
            return ProjectedRuntimeResource(value=delegation_runtime.for_parent(instance))
        workspace = conversations.require_workspace(instance.request.workspace_id)
        if workspace.principal_id != instance.request.principal_id:
            raise PermissionError("runtime workspace belongs to another principal")
        if workspace.kind != "managed" or workspace.managed_path is None or workspace.status != "active":
            raise RuntimeError("runtime workspace is not an active managed workspace")
        if resource_name == "process_runtime":
            if instance.request.runtime_role == "temporary":
                allowed = _delegated_write_paths(
                    root=Path(workspace.managed_path),
                    values=delegations.for_runtime(instance.runtime_instance_id).grant.allowed_write_roots,
                )
                if Path(workspace.managed_path).resolve() not in allowed:
                    raise PermissionError(
                        "temporary process capability requires an explicit full-workspace write grant"
                    )
            return process_resources.acquire(instance, root=Path(workspace.managed_path))
        if instance.request.runtime_role == "temporary":
            allowed = _delegated_write_paths(
                root=Path(workspace.managed_path),
                values=delegations.for_runtime(instance.runtime_instance_id).grant.allowed_write_roots,
            )
            return filesystem_resources.acquire(
                instance,
                root=Path(workspace.managed_path),
                allowed_write_paths=allowed,
                write_scope_enforced=True,
            )
        return filesystem_resources.acquire(instance, root=Path(workspace.managed_path))

    return project


def _browser_session_key(instance: RuntimeInstance) -> str:
    if instance.attempt_id is None:
        raise RuntimeError("browser runtime requires a claimed attempt")
    return f"{instance.generation}:{instance.runtime_instance_id}:{instance.attempt_id}"


def _delegated_write_paths(*, root: Path, values: tuple[str, ...]) -> tuple[Path, ...]:
    workspace_root = root.expanduser().resolve()
    resolved: list[Path] = []
    for value in values:
        candidate = (workspace_root / value).resolve()
        if candidate != workspace_root and workspace_root not in candidate.parents:
            raise PermissionError("delegated write root escapes the workspace boundary")
        if candidate not in resolved:
            resolved.append(candidate)
    return tuple(resolved)


def _runtime_attempt_key(instance: RuntimeInstance) -> str:
    if instance.attempt_id is None:
        raise RuntimeError("runtime resource requires a claimed attempt")
    return f"{instance.generation}:{instance.runtime_instance_id}:{instance.attempt_id}"


def _release_callbacks(callbacks: list[ReleaseCallback]) -> None:
    errors: list[BaseException] = []
    while callbacks:
        callback = callbacks.pop()
        try:
            callback()
        except BaseException as exc:
            errors.append(exc)
    if errors:
        raise BaseExceptionGroup("runtime resource release failed", errors)


def _module_target(value: str) -> tuple[str, str]:
    target = str(value or "").strip()
    if ":" not in target:
        raise ValueError("Python module tool entrypoint must use module:function")
    module_name, function_name = (item.strip() for item in target.rsplit(":", 1))
    if not module_name or not function_name:
        raise ValueError("Python module tool entrypoint must include module and function")
    return module_name, function_name
