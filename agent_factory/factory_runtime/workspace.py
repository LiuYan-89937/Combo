from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from agent_factory.factory_runtime.config import FactoryConfig

WORKSPACE_DIR_NAME = ".agentfactory"


class FactoryWorkspace(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    project_root: Path
    workspace_path: Path

    @classmethod
    def discover(cls, start_path: str | Path | None = None) -> "FactoryWorkspace":
        start = Path(start_path or Path.cwd()).resolve()
        if start.is_file():
            start = start.parent
        for candidate in [start, *start.parents]:
            workspace_path = candidate / WORKSPACE_DIR_NAME
            if workspace_path.exists():
                return cls(project_root=candidate, workspace_path=workspace_path)
        return cls(project_root=start, workspace_path=start / WORKSPACE_DIR_NAME)

    def ensure(self, *, workspace_name: str | None = None) -> FactoryConfig:
        self.workspace_path.mkdir(parents=True, exist_ok=True)
        config_path = self.config_path
        if config_path.exists():
            config = FactoryConfig.load(config_path)
        else:
            config = FactoryConfig.default(workspace_name=workspace_name or self.project_root.name)
            config.save(config_path)

        self.resolve(config.storage.drafts_dir).mkdir(parents=True, exist_ok=True)
        self.resolve("memory").mkdir(parents=True, exist_ok=True)
        self.resolve("traces").mkdir(parents=True, exist_ok=True)
        self.resolve(config.storage.memory_file).parent.mkdir(parents=True, exist_ok=True)
        self.resolve(config.storage.trace_file).parent.mkdir(parents=True, exist_ok=True)
        return config

    @property
    def config_path(self) -> Path:
        return self.workspace_path / "config.yaml"

    def resolve(self, relative_path: str | Path) -> Path:
        path = Path(relative_path)
        if path.is_absolute():
            return path
        return self.workspace_path / path
