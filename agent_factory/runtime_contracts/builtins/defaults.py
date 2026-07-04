from __future__ import annotations

from agent_factory.memory_system import default_agent_memory_config
from agent_factory.memory_system.config import MemoryStoreRuntimeConfig
from agent_factory.runtime_contracts.schema import (
    ContextContract,
    DependenciesContract,
    KnowledgeContract,
    MemoryContract,
    MemoryContractConfig,
    ModelContract,
    ResourcesContract,
    SchedulerContract,
    SchedulerSeedContract,
    SessionContract,
    SessionContractConfig,
    StateContract,
    ToolsContract,
)


def default_session_contract() -> SessionContract:
    return SessionContract(
        config=SessionContractConfig(
            session_root=".agent_runtime/sessions",
            checkpointer_backend="sqlite",
            checkpoint_path=".agent_runtime/checkpoints/agent.sqlite",
        )
    )


def default_tools_contract() -> ToolsContract:
    return ToolsContract()


def default_model_contract() -> ModelContract:
    return ModelContract()


def default_state_contract() -> StateContract:
    return StateContract(enabled=False)


def default_memory_contract() -> MemoryContract:
    config = default_agent_memory_config()
    config = config.model_copy(
        update={
            "store": MemoryStoreRuntimeConfig(backend=config.store.backend, path=".agent_runtime/memory/agent.sqlite"),
            "background": config.background.model_copy(update={"journal_root": ".agent_runtime/memory/jobs"}),
        },
        deep=True,
    )
    return MemoryContract(config=MemoryContractConfig(memory_system=config))


def default_context_contract() -> ContextContract:
    return ContextContract()


def default_knowledge_contract() -> KnowledgeContract:
    return KnowledgeContract()


def default_resources_contract() -> ResourcesContract:
    return ResourcesContract()


def default_dependencies_contract() -> DependenciesContract:
    return DependenciesContract()


def default_scheduler_contract() -> SchedulerContract:
    return SchedulerContract()


def default_scheduler_seed_contract() -> SchedulerSeedContract:
    return SchedulerSeedContract()
