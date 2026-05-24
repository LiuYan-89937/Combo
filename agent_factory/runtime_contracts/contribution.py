from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

from agent_factory.runtime_kernel.bindings import RuntimeServices
from agent_factory.runtime_render import RenderManifest


@dataclass(slots=True)
class RuntimeDiagnostic:
    where: str
    level: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RuntimeContribution:
    services: dict[str, Any] = field(default_factory=dict)
    system_wrappers: list[str] = field(default_factory=list)
    tool_providers: list[Any] = field(default_factory=list)
    node_providers: list[Any] = field(default_factory=list)
    context_sources: list[Any] = field(default_factory=list)
    background_workers: list[Any] = field(default_factory=list)
    event_publishers: list[Any] = field(default_factory=list)
    session_hooks: list[Any] = field(default_factory=list)
    diagnostics: list[RuntimeDiagnostic] = field(default_factory=list)
    session_config: dict[str, Any] = field(default_factory=dict)
    resources: dict[str, Any] = field(default_factory=dict)
    tool_runtime_resources: dict[str, Any] = field(default_factory=dict)
    state_contracts: list[Any] = field(default_factory=list)
    render_manifest: RenderManifest | None = None
    sandbox_contract: dict[str, Any] | None = None
    dependency_plan: dict[str, Any] | None = None


@dataclass(slots=True)
class RuntimeBuildResult:
    services: RuntimeServices
    render_manifest: RenderManifest
    system_wrappers: list[str] = field(default_factory=list)
    session_config: dict[str, Any] = field(default_factory=dict)
    resources: dict[str, Any] = field(default_factory=dict)
    tool_runtime_resources: dict[str, Any] = field(default_factory=dict)
    sandbox_contract: dict[str, Any] = field(default_factory=dict)
    dependency_plan: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[RuntimeDiagnostic] = field(default_factory=list)
    background_workers: list[Any] = field(default_factory=list)
    contracts: dict[str, Any] = field(default_factory=dict)
    node_providers: list[Any] = field(default_factory=list)
    state_contracts: list[Any] = field(default_factory=list)


class RuntimeContributionMergeError(ValueError):
    pass


class RuntimeContributionMerger:
    def __init__(self, *, base_services: RuntimeServices) -> None:
        self._base_services = base_services

    def merge(self, contributions: list[RuntimeContribution]) -> RuntimeBuildResult:
        services = _service_slots(self._base_services)
        diagnostics: list[RuntimeDiagnostic] = []
        background_workers: list[Any] = []
        node_providers: list[Any] = []
        seen_node_impl_ids: set[str] = set()
        state_contracts: list[Any] = []
        system_wrappers: list[str] = []
        seen_system_wrappers: set[str] = set()
        session_config: dict[str, Any] = {}
        resources: dict[str, Any] = {}
        tool_runtime_resources: dict[str, Any] = {}
        sandbox_contract: dict[str, Any] = {}
        dependency_plan: dict[str, Any] = {}
        render_manifest: RenderManifest | None = None
        for contribution in contributions:
            for name, value in contribution.services.items():
                if value is None:
                    continue
                if name not in services:
                    raise RuntimeContributionMergeError(f"unknown runtime service slot: {name}")
                if services[name] is not None and services[name] is not value:
                    raise RuntimeContributionMergeError(f"duplicate runtime service contribution: {name}")
                services[name] = value
            for wrapper_id in contribution.system_wrappers:
                if wrapper_id in seen_system_wrappers:
                    raise RuntimeContributionMergeError(f"duplicate system wrapper contribution: {wrapper_id}")
                seen_system_wrappers.add(wrapper_id)
                system_wrappers.append(wrapper_id)
            for provider in contribution.node_providers:
                provider_id = str(getattr(provider, "provider_id", ""))
                for implementation in provider.implementations():
                    impl_id = str(getattr(implementation, "impl_id", ""))
                    if not impl_id:
                        raise RuntimeContributionMergeError(f"node provider {provider_id} returned implementation without impl_id")
                    if impl_id in seen_node_impl_ids:
                        raise RuntimeContributionMergeError(f"duplicate node implementation contribution: {impl_id}")
                    seen_node_impl_ids.add(impl_id)
                node_providers.append(provider)
            for key, value in contribution.session_config.items():
                if key in session_config and session_config[key] != value:
                    raise RuntimeContributionMergeError(f"conflicting session config: {key}")
                session_config[key] = value
            for key, value in contribution.resources.items():
                _assert_json_serializable_runtime_resource(key, value)
                if key in resources and resources[key] != value:
                    raise RuntimeContributionMergeError(f"conflicting runtime resource: {key}")
                resources[key] = value
            for key, value in contribution.tool_runtime_resources.items():
                if key in tool_runtime_resources and tool_runtime_resources[key] is not value:
                    raise RuntimeContributionMergeError(f"conflicting tool runtime resource: {key}")
                tool_runtime_resources[key] = value
            if contribution.render_manifest is not None:
                if render_manifest is not None and render_manifest != contribution.render_manifest:
                    raise RuntimeContributionMergeError("conflicting render manifest contribution")
                render_manifest = contribution.render_manifest
            if contribution.sandbox_contract is not None:
                if sandbox_contract and sandbox_contract != contribution.sandbox_contract:
                    raise RuntimeContributionMergeError("conflicting sandbox contract contribution")
                sandbox_contract = dict(contribution.sandbox_contract)
            if contribution.dependency_plan is not None:
                if dependency_plan and dependency_plan != contribution.dependency_plan:
                    raise RuntimeContributionMergeError("conflicting dependency plan contribution")
                dependency_plan = dict(contribution.dependency_plan)
            diagnostics.extend(contribution.diagnostics)
            background_workers.extend(contribution.background_workers)
            state_contracts.extend(contribution.state_contracts)
        if render_manifest is None:
            raise RuntimeContributionMergeError("render contract did not provide a render manifest")
        services["runtime_resources"] = dict(resources)
        services["tool_runtime_resources"] = dict(tool_runtime_resources)
        return RuntimeBuildResult(
            services=RuntimeServices(**services),
            render_manifest=render_manifest,
            system_wrappers=system_wrappers,
            session_config=session_config,
            resources=resources,
            tool_runtime_resources=tool_runtime_resources,
            sandbox_contract=sandbox_contract,
            dependency_plan=dependency_plan,
            diagnostics=diagnostics,
            background_workers=background_workers,
            node_providers=node_providers,
            state_contracts=state_contracts,
        )


def _service_slots(services: RuntimeServices) -> dict[str, Any]:
    return {
        "model_service": None,
        "model_operation_service": None,
        "tool_registry": None,
        "memory_store": None,
        "memory_system": None,
        "context_system": None,
        "knowledge_engine": services.knowledge_engine,
        "context_engine": services.context_engine,
        "policy_engine": services.policy_engine,
        "observability_manager": services.observability_manager,
        "checkpointer": None,
        "harness_bridge": services.harness_bridge,
        "scheduler_store": None,
        "scheduler_runtime": None,
        "artifact_store": None,
        "report_store": None,
        "bookmark_store": services.bookmark_store,
        "runtime_resources": dict(services.runtime_resources),
        "tool_runtime_resources": dict(services.tool_runtime_resources),
    }


def _assert_json_serializable_runtime_resource(key: str, value: Any) -> None:
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise RuntimeContributionMergeError(
            f"runtime resource must be JSON serializable: {key}"
        ) from exc
