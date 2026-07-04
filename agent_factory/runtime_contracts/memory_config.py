from __future__ import annotations

from agent_factory.memory_system.config import MemorySystemConfig
from agent_factory.runtime_contracts.builder import RuntimeBuildContext
from agent_factory.runtime_contracts.paths import package_runtime_path_text


def resolve_memory_system_config(
    config: MemorySystemConfig,
    context: RuntimeBuildContext,
) -> MemorySystemConfig:
    store = config.store
    background = config.background
    return config.model_copy(
        update={
            "store": (
                store.model_copy(
                    update={
                        "path": package_runtime_path_text(
                            context,
                            store.path,
                            field_path="memory.config.memory_system.store.path",
                        )
                    }
                )
                if store.backend == "sqlite" and store.path.strip()
                else store
            ),
            "background": background.model_copy(
                update={
                    "journal_root": package_runtime_path_text(
                        context,
                        background.journal_root,
                        field_path="memory.config.memory_system.background.journal_root",
                    )
                }
            ),
        },
        deep=True,
    )
