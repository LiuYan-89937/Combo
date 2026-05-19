from __future__ import annotations

from agent_factory.memory_system import default_agent_memory_config
from agent_factory.runtime_contracts.schema import (
    MemoryContract,
    MemoryContractConfig,
    RenderContract,
    ResourcesContract,
    SandboxRuntimeContract,
    SessionContract,
    SessionContractConfig,
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


def default_memory_contract() -> MemoryContract:
    return MemoryContract(config=MemoryContractConfig(memory_system=default_agent_memory_config()))


def default_render_contract() -> RenderContract:
    return RenderContract()


def default_resources_contract() -> ResourcesContract:
    return ResourcesContract()


def default_sandbox_contract() -> SandboxRuntimeContract:
    return SandboxRuntimeContract()
