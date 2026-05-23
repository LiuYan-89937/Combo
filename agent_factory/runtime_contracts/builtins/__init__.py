from __future__ import annotations

from agent_factory.runtime_contracts.builtins.builders import (
    ContextContractBuilder,
    DependenciesContractBuilder,
    MemoryContractBuilder,
    ModelContractBuilder,
    RenderContractBuilder,
    ResourcesContractBuilder,
    SandboxContractBuilder,
    SchedulerContractBuilder,
    SessionContractBuilder,
    ToolsContractBuilder,
)
from agent_factory.runtime_contracts.builtins.defaults import (
    default_context_contract,
    default_dependencies_contract,
    default_memory_contract,
    default_model_contract,
    default_render_contract,
    default_resources_contract,
    default_sandbox_contract,
    default_scheduler_contract,
    default_session_contract,
    default_tools_contract,
)
from agent_factory.runtime_contracts.registry import RuntimeContractRegistry
from agent_factory.runtime_contracts.schema import (
    ContextContract,
    DependenciesContract,
    MemoryContract,
    ModelContract,
    RenderContract,
    ResourcesContract,
    SandboxRuntimeContract,
    SchedulerContract,
    SessionContract,
    ToolsContract,
)


def default_runtime_contract_registry() -> RuntimeContractRegistry:
    registry = RuntimeContractRegistry()
    registry.register(
        contract_type="session",
        version="session_contract.v0",
        model=SessionContract,
        builder=SessionContractBuilder(),
    )
    registry.register(
        contract_type="tools",
        version="tools_contract.v0",
        model=ToolsContract,
        builder=ToolsContractBuilder(),
    )
    registry.register(
        contract_type="memory",
        version="memory_contract.v0",
        model=MemoryContract,
        builder=MemoryContractBuilder(),
    )
    registry.register(
        contract_type="context",
        version="context_contract.v0",
        model=ContextContract,
        builder=ContextContractBuilder(),
    )
    registry.register(
        contract_type="model",
        version="model_contract.v0",
        model=ModelContract,
        builder=ModelContractBuilder(),
    )
    registry.register(
        contract_type="render",
        version="render_contract.v0",
        model=RenderContract,
        builder=RenderContractBuilder(),
    )
    registry.register(
        contract_type="resources",
        version="resources_contract.v0",
        model=ResourcesContract,
        builder=ResourcesContractBuilder(),
    )
    registry.register(
        contract_type="sandbox",
        version="sandbox_contract.v0",
        model=SandboxRuntimeContract,
        builder=SandboxContractBuilder(),
    )
    registry.register(
        contract_type="scheduler",
        version="scheduler_contract.v0",
        model=SchedulerContract,
        builder=SchedulerContractBuilder(),
    )
    registry.register(
        contract_type="dependencies",
        version="dependencies_contract.v0",
        model=DependenciesContract,
        builder=DependenciesContractBuilder(),
    )
    return registry


__all__ = [
    "default_context_contract",
    "default_dependencies_contract",
    "default_memory_contract",
    "default_model_contract",
    "default_render_contract",
    "default_resources_contract",
    "default_runtime_contract_registry",
    "default_sandbox_contract",
    "default_scheduler_contract",
    "default_session_contract",
    "default_tools_contract",
]
