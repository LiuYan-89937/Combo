from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from threading import RLock
from types import MappingProxyType
from typing import Literal, Protocol

from langchain_core.tools import BaseTool

from combo.dynamic_runtime.capability_definitions import ToolRuntimePolicy
from combo.runtime_protocol import (
    CapabilityProjectionSnapshot,
    CapabilitySnapshot,
    CapabilityToolAliasBinding,
    RuntimeInstance,
)


SnapshotToolKind = Literal["tool", "mcp_tool"]
ReleaseCallback = Callable[[], None]


class SnapshotToolRegistryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MaterializedSnapshotTool:
    model_alias: str
    capability_id: str
    kind: SnapshotToolKind
    revision: int
    content_digest: str
    tool: BaseTool
    runtime_policy: ToolRuntimePolicy
    release_callback: ReleaseCallback
    system_available: bool = False

    def __post_init__(self) -> None:
        if not self.model_alias.strip() or not self.capability_id.strip():
            raise ValueError("materialized snapshot tool requires alias and capability identity")
        if self.revision < 1 or not self.content_digest.strip():
            raise ValueError("materialized snapshot tool requires an immutable capability revision")
        if self.tool.name != self.model_alias:
            raise ValueError("materialized BaseTool name must equal its snapshot model alias")
        if not callable(self.release_callback):
            raise TypeError("materialized snapshot tool requires a lifecycle release callback")


class CapabilityToolProjectionMaterializer(Protocol):
    @property
    def kind(self) -> SnapshotToolKind:
        ...

    def materialize(
        self,
        *,
        projection: CapabilityProjectionSnapshot,
        capability_snapshot: CapabilitySnapshot,
        runtime_instance: RuntimeInstance,
    ) -> tuple[MaterializedSnapshotTool, ...]:
        """Materialize only the supplied immutable projection; current stores are unavailable."""
        ...


class ImmutableSnapshotToolRegistry:
    def __init__(self, tools: tuple[MaterializedSnapshotTool, ...]) -> None:
        aliases = tuple(item.model_alias for item in tools)
        if len(aliases) != len(set(aliases)):
            raise SnapshotToolRegistryError("snapshot tool registry aliases must be unique")
        self._ordered_aliases = aliases
        self._tools = MappingProxyType({item.model_alias: item for item in tools})

    def list_tool_ids(self) -> list[str]:
        return list(self._ordered_aliases)

    def system_tool_ids(self) -> list[str]:
        return [
            alias
            for alias in self._ordered_aliases
            if self._tools[alias].system_available
        ]

    def model_tools(self, tool_ids: list[str] | set[str] | None = None) -> list[BaseTool]:
        aliases = self._ordered_aliases if tool_ids is None else tuple(tool_ids)
        unknown = [alias for alias in aliases if alias not in self._tools]
        if unknown:
            raise SnapshotToolRegistryError(
                "tool aliases are absent from the bound capability snapshot: "
                + ", ".join(sorted(set(unknown)))
            )
        selected = set(aliases)
        return [
            self._tools[alias].tool
            for alias in self._ordered_aliases
            if alias in selected
        ]

    def tool_for_capability(self, capability_id: str) -> BaseTool:
        requested = str(capability_id or "").strip()
        if not requested:
            raise ValueError("capability_id must not be empty")
        matches = tuple(
            item.tool
            for item in self._tools.values()
            if item.capability_id == requested
        )
        if not matches:
            raise SnapshotToolRegistryError(f"snapshot has no Tool for capability: {requested}")
        if len(matches) > 1:
            raise SnapshotToolRegistryError(f"snapshot has ambiguous Tool aliases for capability: {requested}")
        return next(iter(matches))


@dataclass(slots=True)
class SnapshotToolRegistryLease:
    runtime_instance_id: str
    snapshot_id: str
    snapshot_digest: str
    registry: ImmutableSnapshotToolRegistry
    _release_callbacks: tuple[ReleaseCallback, ...]
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
    _released: bool = field(default=False, init=False, repr=False)

    @property
    def released(self) -> bool:
        with self._lock:
            return self._released

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
        errors: list[BaseException] = []
        for callback in reversed(self._release_callbacks):
            try:
                callback()
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise SnapshotToolRegistryError(
                f"snapshot tool registry release failed for {len(errors)} resource(s)"
            ) from errors[0]


@dataclass(frozen=True, slots=True)
class RuntimeToolRegistryBinding:
    runtime_instance_id: str
    snapshot_id: str
    snapshot_digest: str
    registry: ImmutableSnapshotToolRegistry


class RuntimeScopedToolRegistry:
    def __init__(self) -> None:
        self._binding: ContextVar[RuntimeToolRegistryBinding | None] = ContextVar(
            "dynamic_runtime_tool_registry_binding",
            default=None,
        )

    @contextmanager
    def bind(self, lease: SnapshotToolRegistryLease) -> Iterator[None]:
        if lease.released:
            raise SnapshotToolRegistryError("cannot bind a released snapshot tool registry lease")
        binding = RuntimeToolRegistryBinding(
            runtime_instance_id=lease.runtime_instance_id,
            snapshot_id=lease.snapshot_id,
            snapshot_digest=lease.snapshot_digest,
            registry=lease.registry,
        )
        current = self._binding.get()
        if current is not None and current != binding:
            raise SnapshotToolRegistryError("runtime context already carries a different tool registry")
        token: Token[RuntimeToolRegistryBinding | None] = self._binding.set(binding)
        try:
            yield
        finally:
            self._binding.reset(token)

    def list_tool_ids(self) -> list[str]:
        return self._require_binding().registry.list_tool_ids()

    def system_tool_ids(self) -> list[str]:
        return self._require_binding().registry.system_tool_ids()

    def model_tools(self, tool_ids: list[str] | set[str] | None = None) -> list[BaseTool]:
        return self._require_binding().registry.model_tools(tool_ids)

    def _require_binding(self) -> RuntimeToolRegistryBinding:
        binding = self._binding.get()
        if binding is None:
            raise SnapshotToolRegistryError("runtime tool registry is not bound to an execution snapshot")
        return binding


class SnapshotToolRegistryFactory:
    def __init__(self, materializers: Iterable[CapabilityToolProjectionMaterializer]) -> None:
        registered: dict[SnapshotToolKind, CapabilityToolProjectionMaterializer] = {}
        for materializer in materializers:
            if materializer.kind in registered:
                raise ValueError(f"duplicate snapshot tool materializer: {materializer.kind}")
            registered[materializer.kind] = materializer
        required: set[SnapshotToolKind] = {"tool", "mcp_tool"}
        missing = required - set(registered)
        if missing:
            raise ValueError("missing snapshot tool materializers: " + ", ".join(sorted(missing)))
        self._materializers: Mapping[SnapshotToolKind, CapabilityToolProjectionMaterializer] = (
            MappingProxyType(registered)
        )

    def materialize(
        self,
        *,
        capability_snapshot: CapabilitySnapshot,
        runtime_instance: RuntimeInstance,
    ) -> SnapshotToolRegistryLease:
        _validate_snapshot_instance(capability_snapshot, runtime_instance)
        bindings_by_capability = _bindings_by_capability(capability_snapshot)
        materialized: list[MaterializedSnapshotTool] = []
        try:
            for projection in capability_snapshot.projections:
                if projection.kind not in {"tool", "mcp_tool"}:
                    continue
                expected = bindings_by_capability.get(projection.capability_id, ())
                if not expected:
                    raise SnapshotToolRegistryError(
                        f"tool projection has no model alias binding: {projection.capability_id}"
                    )
                items = self._materializers[projection.kind].materialize(
                    projection=projection,
                    capability_snapshot=capability_snapshot,
                    runtime_instance=runtime_instance,
                )
                materialized.extend(items)
                _validate_materialized_projection(projection, expected, items)
            _validate_complete_surface(capability_snapshot, materialized)
            projected_tools = tuple(_apply_runtime_policy_metadata(item) for item in materialized)
        except BaseException as exc:
            release_errors = _release_materialized_tools(materialized)
            if release_errors:
                raise BaseExceptionGroup(
                    "snapshot tool materialization and cleanup failed",
                    [exc, *release_errors],
                )
            raise
        return SnapshotToolRegistryLease(
            runtime_instance_id=runtime_instance.runtime_instance_id,
            snapshot_id=capability_snapshot.snapshot_id,
            snapshot_digest=capability_snapshot.content_digest,
            registry=ImmutableSnapshotToolRegistry(projected_tools),
            _release_callbacks=tuple(item.release_callback for item in materialized),
        )


def _validate_snapshot_instance(snapshot: CapabilitySnapshot, instance: RuntimeInstance) -> None:
    if instance.capability_snapshot_id != snapshot.snapshot_id:
        raise SnapshotToolRegistryError("runtime instance does not reference the supplied capability snapshot")
    if instance.request.capability_snapshot_id != snapshot.snapshot_id:
        raise SnapshotToolRegistryError("runtime request does not reference the supplied capability snapshot")


def _bindings_by_capability(
    snapshot: CapabilitySnapshot,
) -> dict[str, tuple[CapabilityToolAliasBinding, ...]]:
    grouped: dict[str, list[CapabilityToolAliasBinding]] = {}
    for binding in snapshot.tool_aliases:
        grouped.setdefault(binding.capability_id, []).append(binding)
    return {key: tuple(value) for key, value in grouped.items()}


def _validate_materialized_projection(
    projection: CapabilityProjectionSnapshot,
    expected: tuple[CapabilityToolAliasBinding, ...],
    materialized: tuple[MaterializedSnapshotTool, ...],
) -> None:
    if not isinstance(materialized, tuple):
        raise TypeError("snapshot tool materializer must return a tuple")
    actual = tuple(
        (
            item.model_alias,
            item.capability_id,
            item.kind,
            item.revision,
            item.content_digest,
        )
        for item in materialized
    )
    required = tuple(
        (
            item.model_alias,
            item.capability_id,
            item.kind,
            item.revision,
            item.content_digest,
        )
        for item in expected
    )
    if actual != required:
        raise SnapshotToolRegistryError(
            f"materialized tool surface differs from projection: {projection.capability_id}"
        )


def _validate_complete_surface(
    snapshot: CapabilitySnapshot,
    materialized: list[MaterializedSnapshotTool],
) -> None:
    actual = tuple(item.model_alias for item in materialized)
    if actual != snapshot.tool_ids:
        raise SnapshotToolRegistryError("materialized registry differs from ordered snapshot tool surface")


def _apply_runtime_policy_metadata(item: MaterializedSnapshotTool) -> MaterializedSnapshotTool:
    metadata = dict(item.tool.metadata or {})
    combo_metadata = dict(metadata.get("combo") or {})
    policy = item.runtime_policy
    combo_metadata.update(
        {
            "tool_id": item.model_alias,
            "capability_id": item.capability_id,
            "capability_revision": item.revision,
            "capability_content_digest": item.content_digest,
            "approval": policy.approval,
            "risk_level": policy.risk_level,
            "concurrent": policy.allow_parallel_calls,
            "max_parallel_calls": policy.max_parallel_calls,
            "serialization_key": policy.serialization_key,
            "timeout_seconds": policy.timeout_seconds,
            "output_projection": policy.output_projection,
            "output_max_model_chars": policy.output_max_model_chars,
            "retain_raw_output": policy.retain_raw_output,
        }
    )
    metadata["combo"] = combo_metadata
    tool = item.tool.model_copy(update={"metadata": metadata})
    return MaterializedSnapshotTool(
        model_alias=item.model_alias,
        capability_id=item.capability_id,
        kind=item.kind,
        revision=item.revision,
        content_digest=item.content_digest,
        tool=tool,
        runtime_policy=item.runtime_policy,
        release_callback=item.release_callback,
        system_available=item.system_available,
    )


def _release_materialized_tools(
    items: list[MaterializedSnapshotTool],
) -> tuple[BaseException, ...]:
    errors: list[BaseException] = []
    for item in reversed(items):
        try:
            item.release_callback()
        except BaseException as exc:
            errors.append(exc)
    return tuple(errors)
