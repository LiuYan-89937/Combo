from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from threading import RLock
from types import MappingProxyType
from typing import Any, Protocol

from agent_factory.dynamic_runtime.capability_definitions import (
    MCPToolDefinition,
    ToolDefinition,
    ToolRuntimePolicy,
)
from agent_factory.dynamic_runtime.snapshot_tool_materializers import MaterializedToolRuntime
from agent_factory.runtime_protocol import (
    CapabilityProjectionSnapshot,
    CapabilitySnapshot,
    RuntimeInstance,
)
from agent_factory.tooling.approval_policy import (
    ToolApprovalOverrideConfig,
    ToolApprovalPolicyConfig,
)
from agent_factory.tooling.compiler import ToolCompiler
from agent_factory.tooling.gateway import ToolApprovalTrustResolver
from agent_factory.tooling.output_store import (
    TOOL_OUTPUT_STORE_RESOURCE,
    ToolOutputPolicy,
    ToolOutputStore,
)
from agent_factory.tooling.spec import ToolOutputCompressionConfig, ToolSpec


ToolEntrypoint = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
ReleaseCallback = Callable[[], None]


@dataclass(frozen=True, slots=True)
class ToolEntrypointLease:
    entrypoint: ToolEntrypoint
    release_callback: ReleaseCallback

    def __post_init__(self) -> None:
        if not callable(self.entrypoint) or not callable(self.release_callback):
            raise TypeError("tool entrypoint lease requires callable entrypoint and release callback")


@dataclass(frozen=True, slots=True)
class ToolResourceLease:
    resources: Mapping[str, Any]
    release_callback: ReleaseCallback

    def __post_init__(self) -> None:
        if not callable(self.release_callback):
            raise TypeError("tool resource lease requires a release callback")
        normalized = {str(key).strip(): value for key, value in self.resources.items()}
        if any(not key for key in normalized) or len(normalized) != len(self.resources):
            raise ValueError("tool resource lease names must be non-empty and unique")
        object.__setattr__(self, "resources", MappingProxyType(normalized))


@dataclass(frozen=True, slots=True)
class ToolOutputRuntimeLease:
    store: ToolOutputStore | None
    compression_model_resolver: Callable[[], Any] | None
    release_callback: ReleaseCallback

    def __post_init__(self) -> None:
        if not callable(self.release_callback):
            raise TypeError("tool output runtime lease requires a release callback")
        if self.compression_model_resolver is not None and not callable(self.compression_model_resolver):
            raise TypeError("compression_model_resolver must be callable")


@dataclass(frozen=True, slots=True)
class ToolApprovalRuntimeLease:
    trust: ToolApprovalTrustResolver | None
    release_callback: ReleaseCallback

    def __post_init__(self) -> None:
        if not callable(self.release_callback):
            raise TypeError("tool approval runtime lease requires a release callback")


class SnapshotToolEntrypointResolver(Protocol):
    def acquire(
        self,
        *,
        definition: ToolDefinition,
        projection: CapabilityProjectionSnapshot,
        capability_snapshot: CapabilitySnapshot,
        runtime_instance: RuntimeInstance,
    ) -> ToolEntrypointLease:
        ...


class SnapshotMCPEntrypointResolver(Protocol):
    def acquire(
        self,
        *,
        definition: MCPToolDefinition,
        projection: CapabilityProjectionSnapshot,
        capability_snapshot: CapabilitySnapshot,
        runtime_instance: RuntimeInstance,
    ) -> ToolEntrypointLease:
        ...


class SnapshotToolResourceResolver(Protocol):
    def acquire(
        self,
        *,
        definition: ToolDefinition,
        projection: CapabilityProjectionSnapshot,
        capability_snapshot: CapabilitySnapshot,
        runtime_instance: RuntimeInstance,
    ) -> ToolResourceLease:
        ...


class SnapshotToolOutputResolver(Protocol):
    def acquire(
        self,
        *,
        projection: CapabilityProjectionSnapshot,
        capability_snapshot: CapabilitySnapshot,
        runtime_instance: RuntimeInstance,
        retain_raw_output: bool,
    ) -> ToolOutputRuntimeLease:
        ...


class SnapshotToolApprovalResolver(Protocol):
    def acquire(
        self,
        *,
        projection: CapabilityProjectionSnapshot,
        capability_snapshot: CapabilitySnapshot,
        runtime_instance: RuntimeInstance,
    ) -> ToolApprovalRuntimeLease:
        ...


class ExplicitToolCapabilityRuntimeAdapter:
    def __init__(
        self,
        *,
        entrypoints: SnapshotToolEntrypointResolver,
        resources: SnapshotToolResourceResolver,
        outputs: SnapshotToolOutputResolver,
        approvals: SnapshotToolApprovalResolver,
        maximum_argument_revisions: int,
    ) -> None:
        if maximum_argument_revisions < 1:
            raise ValueError("maximum_argument_revisions must be positive")
        self._entrypoints = entrypoints
        self._resources = resources
        self._outputs = outputs
        self._approvals = approvals
        self._maximum_argument_revisions = maximum_argument_revisions

    def materialize(
        self,
        *,
        definition: ToolDefinition,
        projection: CapabilityProjectionSnapshot,
        capability_snapshot: CapabilitySnapshot,
        runtime_instance: RuntimeInstance,
    ) -> MaterializedToolRuntime:
        entrypoint = self._entrypoints.acquire(
            definition=definition,
            projection=projection,
            capability_snapshot=capability_snapshot,
            runtime_instance=runtime_instance,
        )
        releases = _CompositeRelease(entrypoint.release_callback)
        try:
            resources = self._resources.acquire(
                definition=definition,
                projection=projection,
                capability_snapshot=capability_snapshot,
                runtime_instance=runtime_instance,
            )
            releases.add(resources.release_callback)
            output = self._outputs.acquire(
                projection=projection,
                capability_snapshot=capability_snapshot,
                runtime_instance=runtime_instance,
                retain_raw_output=definition.runtime_policy.retain_raw_output,
            )
            _validate_output_retention(output, definition.runtime_policy)
            releases.add(output.release_callback)
            approval = self._approvals.acquire(
                projection=projection,
                capability_snapshot=capability_snapshot,
                runtime_instance=runtime_instance,
            )
            releases.add(approval.release_callback)
            tool = _compile_tool(
                definition=definition,
                entrypoint=entrypoint.entrypoint,
                resources=resources.resources,
                output=output,
                approval=approval,
                runtime_instance=runtime_instance,
                maximum_argument_revisions=self._maximum_argument_revisions,
            )
        except BaseException as exc:
            _raise_with_release_errors(exc, releases.release_errors())
        return MaterializedToolRuntime(tool=tool, release_callback=releases.release)


class ExplicitMCPToolCapabilityRuntimeAdapter:
    def __init__(
        self,
        *,
        entrypoints: SnapshotMCPEntrypointResolver,
        outputs: SnapshotToolOutputResolver,
        approvals: SnapshotToolApprovalResolver,
        maximum_argument_revisions: int,
    ) -> None:
        if maximum_argument_revisions < 1:
            raise ValueError("maximum_argument_revisions must be positive")
        self._entrypoints = entrypoints
        self._outputs = outputs
        self._approvals = approvals
        self._maximum_argument_revisions = maximum_argument_revisions

    def materialize(
        self,
        *,
        definition: MCPToolDefinition,
        projection: CapabilityProjectionSnapshot,
        capability_snapshot: CapabilitySnapshot,
        runtime_instance: RuntimeInstance,
    ) -> MaterializedToolRuntime:
        entrypoint = self._entrypoints.acquire(
            definition=definition,
            projection=projection,
            capability_snapshot=capability_snapshot,
            runtime_instance=runtime_instance,
        )
        releases = _CompositeRelease(entrypoint.release_callback)
        try:
            output = self._outputs.acquire(
                projection=projection,
                capability_snapshot=capability_snapshot,
                runtime_instance=runtime_instance,
                retain_raw_output=definition.runtime_policy.retain_raw_output,
            )
            _validate_output_retention(output, definition.runtime_policy)
            releases.add(output.release_callback)
            approval = self._approvals.acquire(
                projection=projection,
                capability_snapshot=capability_snapshot,
                runtime_instance=runtime_instance,
            )
            releases.add(approval.release_callback)
            tool = _compile_mcp_tool(
                definition=definition,
                entrypoint=entrypoint.entrypoint,
                output=output,
                approval=approval,
                runtime_instance=runtime_instance,
                maximum_argument_revisions=self._maximum_argument_revisions,
            )
        except BaseException as exc:
            _raise_with_release_errors(exc, releases.release_errors())
        return MaterializedToolRuntime(tool=tool, release_callback=releases.release)


def _compile_tool(
    *,
    definition: ToolDefinition,
    entrypoint: ToolEntrypoint,
    resources: Mapping[str, Any],
    output: ToolOutputRuntimeLease,
    approval: ToolApprovalRuntimeLease,
    runtime_instance: RuntimeInstance,
    maximum_argument_revisions: int,
):
    expected_resources = tuple(item.name for item in definition.resource_bindings)
    if set(resources) != set(expected_resources):
        raise ValueError("materialized Tool resources differ from the immutable resource bindings")
    spec = ToolSpec(
        id=definition.model_alias,
        description=definition.model_description,
        entrypoint=definition.implementation.entrypoint,
        input_schema=definition.input_schema,
        output_schema=definition.output_schema,
        resources={name: name for name in expected_resources},
        risk_level=definition.runtime_policy.risk_level,
        concurrent=definition.runtime_policy.allow_parallel_calls,
        permission_scope="capability",
        permission_tags=list(definition.effects),
        output_compression=ToolOutputCompressionConfig(
            max_model_chars=definition.runtime_policy.output_max_model_chars,
        ),
        output_projection=definition.runtime_policy.output_projection,
        sensitive_argument_paths=list(definition.sensitive_argument_paths),
    )
    return _compiler(
        spec=spec,
        runtime_policy=definition.runtime_policy,
        runtime_instance=runtime_instance,
        resources=resources,
        output=output,
        approval=approval,
        maximum_argument_revisions=maximum_argument_revisions,
    ).compile_resolved(spec, entrypoint=entrypoint)


def _compile_mcp_tool(
    *,
    definition: MCPToolDefinition,
    entrypoint: ToolEntrypoint,
    output: ToolOutputRuntimeLease,
    approval: ToolApprovalRuntimeLease,
    runtime_instance: RuntimeInstance,
    maximum_argument_revisions: int,
):
    spec = ToolSpec(
        id=definition.model_alias,
        description=definition.model_description,
        entrypoint=f"mcp:{definition.server_capability_id}/{definition.upstream_tool_name}",
        input_schema=definition.input_schema.canonical_schema,
        output_schema=definition.output_schema.canonical_schema,
        risk_level=definition.runtime_policy.risk_level,
        concurrent=definition.runtime_policy.allow_parallel_calls,
        permission_scope="capability",
        output_compression=ToolOutputCompressionConfig(
            max_model_chars=definition.runtime_policy.output_max_model_chars,
        ),
        output_projection=definition.runtime_policy.output_projection,
    )
    return _compiler(
        spec=spec,
        runtime_policy=definition.runtime_policy,
        runtime_instance=runtime_instance,
        resources={},
        output=output,
        approval=approval,
        maximum_argument_revisions=maximum_argument_revisions,
    ).compile_resolved(spec, entrypoint=entrypoint)


def _compiler(
    *,
    spec: ToolSpec,
    runtime_policy: ToolRuntimePolicy,
    runtime_instance: RuntimeInstance,
    resources: Mapping[str, Any],
    output: ToolOutputRuntimeLease,
    approval: ToolApprovalRuntimeLease,
    maximum_argument_revisions: int,
) -> ToolCompiler:
    compiler_resources = dict(resources)
    if output.store is not None:
        if TOOL_OUTPUT_STORE_RESOURCE in compiler_resources:
            raise ValueError("tool resources conflict with the output store resource")
        compiler_resources[TOOL_OUTPUT_STORE_RESOURCE] = output.store
    return ToolCompiler(
        resources=compiler_resources,
        approval_policy=_approval_policy(
            alias=spec.id,
            runtime_policy=runtime_policy,
            approval_mode=runtime_instance.request.approval_mode,
        ),
        max_revisions=maximum_argument_revisions,
        output_policy=ToolOutputPolicy(max_model_chars=runtime_policy.output_max_model_chars),
        compression_model_resolver=output.compression_model_resolver,
        approval_trust_store=approval.trust,
    )


def _approval_policy(
    *,
    alias: str,
    runtime_policy: ToolRuntimePolicy,
    approval_mode: str,
) -> ToolApprovalPolicyConfig:
    if approval_mode == "always_approval":
        levels = {"low": "ask", "medium": "ask", "high": "ask"}
        action = "deny" if runtime_policy.approval == "deny" else "ask"
    elif approval_mode == "auto":
        levels = {"low": "allow", "medium": "allow", "high": "allow"}
        action = "deny" if runtime_policy.approval == "deny" else "allow"
    elif approval_mode == "ask":
        levels = {"low": "allow", "medium": "allow", "high": "ask"}
        action = runtime_policy.approval
    else:
        raise ValueError(f"unsupported runtime approval mode: {approval_mode}")
    return ToolApprovalPolicyConfig(
        mode="custom",
        **levels,
        tool_overrides={
            alias: ToolApprovalOverrideConfig(
                risk_level=runtime_policy.risk_level,
                approval=action,
            )
        },
    )


def _validate_output_retention(
    output: ToolOutputRuntimeLease,
    runtime_policy: ToolRuntimePolicy,
) -> None:
    if runtime_policy.retain_raw_output and output.store is None:
        raise ValueError("tool policy requires raw output retention but no output store was leased")
    if not runtime_policy.retain_raw_output and output.store is not None:
        raise ValueError("tool policy forbids raw output retention but an output store was leased")


@dataclass(slots=True)
class _CompositeRelease:
    _callbacks: list[ReleaseCallback] = field(default_factory=list)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
    _released: bool = field(default=False, init=False, repr=False)

    def __init__(self, *callbacks: ReleaseCallback) -> None:
        self._callbacks = list(callbacks)
        self._lock = RLock()
        self._released = False

    def add(self, callback: ReleaseCallback) -> None:
        if not callable(callback):
            raise TypeError("release callback must be callable")
        with self._lock:
            if self._released:
                raise RuntimeError("cannot add a callback to a released lease")
            self._callbacks.append(callback)

    def release_errors(self) -> tuple[BaseException, ...]:
        with self._lock:
            if self._released:
                return ()
            self._released = True
            callbacks = tuple(reversed(self._callbacks))
        errors: list[BaseException] = []
        for callback in callbacks:
            try:
                callback()
            except BaseException as exc:
                errors.append(exc)
        return tuple(errors)

    def release(self) -> None:
        errors = self.release_errors()
        if errors:
            raise RuntimeError(f"tool runtime release failed for {len(errors)} resource(s)") from errors[0]


def _raise_with_release_errors(
    cause: BaseException,
    release_errors: tuple[BaseException, ...],
) -> None:
    if release_errors:
        raise BaseExceptionGroup(
            "tool materialization and resource cleanup failed",
            [cause, *release_errors],
        )
    raise cause
