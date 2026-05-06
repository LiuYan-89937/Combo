from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from agent_factory.factory_runtime.config import FactoryConfig
from agent_factory.factory_runtime.trace import FactoryTraceStore
from agent_factory.factory_runtime.workspace import FactoryWorkspace


class FactoryRunContext(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    run_id: str
    workspace: FactoryWorkspace
    config: FactoryConfig
    trace_store: FactoryTraceStore

    @classmethod
    def create(
        cls,
        *,
        run_id: str | None = None,
        start_path: str | Path | None = None,
    ) -> "FactoryRunContext":
        workspace = FactoryWorkspace.discover(start_path)
        config = workspace.ensure()
        trace_path = workspace.resolve(config.trace_file)
        return cls(
            run_id=run_id or str(uuid4()),
            workspace=workspace,
            config=config,
            trace_store=FactoryTraceStore(trace_path),
        )

    @property
    def workspace_path(self) -> Path:
        return self.workspace.workspace_path

    @property
    def trace_path(self) -> Path:
        return self.workspace.resolve(self.config.trace_file)
