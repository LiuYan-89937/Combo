from __future__ import annotations

from pathlib import Path

from pydantic import ConfigDict

from agent_factory.core.types import JsonDumpMixin
from agent_factory.factory_runtime import FactoryConfig, FactoryWorkspace


class InitFactoryRequest(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    start_path: Path | None = None


class InitFactoryResult(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    workspace_path: Path
    config_path: Path
    memory_path: Path
    trace_path: Path
    drafts_path: Path
    config: FactoryConfig


class InitFactoryService:
    def init_factory(self, request: InitFactoryRequest | None = None) -> InitFactoryResult:
        request = request or InitFactoryRequest()
        workspace = FactoryWorkspace.discover(request.start_path)
        config = workspace.ensure()
        return InitFactoryResult(
            workspace_path=workspace.workspace_path,
            config_path=workspace.config_path,
            memory_path=workspace.resolve(config.storage.memory_file),
            trace_path=workspace.resolve(config.storage.trace_file),
            drafts_path=workspace.resolve(config.storage.drafts_dir),
            config=config,
        )
