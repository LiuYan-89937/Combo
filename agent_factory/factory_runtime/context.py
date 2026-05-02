from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from agent_factory.factory_runtime.config import FactoryConfig
from agent_factory.factory_runtime.memory import FactoryMemoryStore
from agent_factory.factory_runtime.tools import FactoryToolRegistry
from agent_factory.factory_runtime.trace import FactoryTraceStore
from agent_factory.factory_runtime.workspace import FactoryWorkspace


class FactoryRunContext(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    run_id: str
    workspace: FactoryWorkspace
    config: FactoryConfig
    memory_store: FactoryMemoryStore
    trace_store: FactoryTraceStore
    tool_registry: FactoryToolRegistry

    @classmethod
    def create(
        cls,
        *,
        run_id: str | None = None,
        start_path: str | Path | None = None,
    ) -> "FactoryRunContext":
        workspace = FactoryWorkspace.discover(start_path)
        config = workspace.ensure()
        memory_path = workspace.resolve(config.storage.memory_file)
        trace_path = workspace.resolve(config.storage.trace_file)
        return cls(
            run_id=run_id or str(uuid4()),
            workspace=workspace,
            config=config,
            memory_store=FactoryMemoryStore(
                memory_path,
                enabled=config.memory.enabled,
            ),
            trace_store=FactoryTraceStore(
                trace_path,
                enabled=config.trace.enabled,
                redact=config.trace.redact_secrets,
            ),
            tool_registry=FactoryToolRegistry(),
        )

    @property
    def workspace_path(self) -> Path:
        return self.workspace.workspace_path

    @property
    def memory_path(self) -> Path:
        return self.workspace.resolve(self.config.storage.memory_file)

    @property
    def trace_path(self) -> Path:
        return self.workspace.resolve(self.config.storage.trace_file)

    @property
    def drafts_path(self) -> Path:
        return self.workspace.resolve(self.config.storage.drafts_dir)
