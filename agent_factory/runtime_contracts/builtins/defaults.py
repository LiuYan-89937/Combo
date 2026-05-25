from __future__ import annotations

from agent_factory.memory_system import default_agent_memory_config
from agent_factory.memory_system.config import MemoryStoreRuntimeConfig
from agent_factory.runtime_contracts.schema import (
    ArtifactContract,
    ContextContract,
    DependenciesContract,
    KnowledgeContract,
    MemoryContract,
    MemoryContractConfig,
    ModelContract,
    NodeProviderContract,
    RenderContract,
    ResourcesContract,
    SandboxRuntimeContract,
    SchedulerContract,
    SessionContract,
    SessionContractConfig,
    StateContract,
    ToolsContract,
    TraceContract,
)


def default_session_contract() -> SessionContract:
    return SessionContract(
        config=SessionContractConfig(
            session_root="/runtime/sessions",
            checkpointer_backend="sqlite",
            checkpoint_path="/runtime/checkpoints/agent.sqlite",
        )
    )


def default_tools_contract() -> ToolsContract:
    return ToolsContract()


def default_model_contract() -> ModelContract:
    return ModelContract()


def default_state_contract() -> StateContract:
    return StateContract(enabled=False)


def default_node_provider_contract() -> NodeProviderContract:
    return NodeProviderContract()


def default_artifact_contract() -> ArtifactContract:
    return ArtifactContract()


def default_memory_contract() -> MemoryContract:
    config = default_agent_memory_config()
    config = config.model_copy(
        update={
            "store": MemoryStoreRuntimeConfig(backend=config.store.backend, path="/runtime/memory/agent.sqlite"),
            "background": config.background.model_copy(update={"journal_root": "/runtime/memory/jobs"}),
        },
        deep=True,
    )
    return MemoryContract(config=MemoryContractConfig(memory_system=config))


def default_context_contract() -> ContextContract:
    return ContextContract()


def default_trace_contract() -> TraceContract:
    return TraceContract()


def default_knowledge_contract() -> KnowledgeContract:
    return KnowledgeContract()


def default_render_contract() -> RenderContract:
    return RenderContract()


def default_resources_contract() -> ResourcesContract:
    return ResourcesContract()


def default_sandbox_contract() -> SandboxRuntimeContract:
    return SandboxRuntimeContract()


def default_dependencies_contract() -> DependenciesContract:
    return DependenciesContract()


def default_scheduler_contract() -> SchedulerContract:
    return SchedulerContract()
