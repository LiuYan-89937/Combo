from __future__ import annotations

from collections.abc import Callable, Mapping
import importlib
from pathlib import Path
from types import MappingProxyType
from typing import Any

from agent_factory.dynamic_runtime.capability_definitions import MCPToolDefinition, ToolDefinition
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


ReleaseCallback = Callable[[], None]
RuntimeResourceFactory = Callable[[RuntimeInstance], Any]


def release_borrowed_runtime_resource() -> None:
    return None


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
        return ToolEntrypointLease(
            entrypoint=function,
            release_callback=release_borrowed_runtime_resource,
        )


class UnavailableMCPEntrypointResolver(SnapshotMCPEntrypointResolver):
    """Fail closed until a revision-bound MCP session lease is provided."""

    def acquire(
        self,
        *,
        definition: MCPToolDefinition,
        projection: CapabilityProjectionSnapshot,
        capability_snapshot: CapabilitySnapshot,
        runtime_instance: RuntimeInstance,
    ) -> ToolEntrypointLease:
        raise RuntimeError(
            f"MCP capability has no revision-bound session adapter: {projection.capability_id}@{projection.revision}"
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
        for name in definition.runtime_resources:
            factory = self._factories.get(name)
            if factory is None:
                raise RuntimeError(f"runtime resource projector is unavailable: {name}")
            resources[name] = factory(runtime_instance)
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
        return ToolResourceLease(
            resources=resources,
            release_callback=release_borrowed_runtime_resource,
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


def runtime_resource_factory(conversations: ConversationStore, resource_name: str) -> RuntimeResourceFactory:
    if resource_name not in {"filesystem", "process_runtime", "runtime_identity"}:
        raise ValueError(f"unsupported runtime resource: {resource_name}")

    def project(instance: RuntimeInstance) -> dict[str, Any]:
        if resource_name == "runtime_identity":
            request = instance.request
            if instance.attempt_id is None:
                raise RuntimeError("runtime identity requires a claimed attempt")
            return {
                "principal_id": request.principal_id,
                "request_id": request.request_id,
                "runtime_instance_id": instance.runtime_instance_id,
                "attempt_id": instance.attempt_id,
                "session_id": request.session_id,
                "turn_id": request.turn_id,
                "workspace_id": request.workspace_id,
                "task_revision": request.task_revision,
                "generation": instance.generation,
            }
        workspace = conversations.require_workspace(instance.request.workspace_id)
        if workspace.principal_id != instance.request.principal_id:
            raise PermissionError("runtime workspace belongs to another principal")
        if workspace.kind != "managed" or workspace.managed_path is None or workspace.status != "active":
            raise RuntimeError("runtime workspace is not an active managed workspace")
        return {"root": workspace.managed_path, "allow_external": False}

    return project


def _module_target(value: str) -> tuple[str, str]:
    target = str(value or "").strip()
    if ":" not in target:
        raise ValueError("Python module tool entrypoint must use module:function")
    module_name, function_name = (item.strip() for item in target.rsplit(":", 1))
    if not module_name or not function_name:
        raise ValueError("Python module tool entrypoint must include module and function")
    return module_name, function_name
