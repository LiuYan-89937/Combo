from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from ruamel.yaml import YAML


class FactoryStorageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    backend: Literal["filesystem"] = "filesystem"
    drafts_dir: str = "packages/drafts"
    memory_file: str = "memory/factory_memory.jsonl"
    trace_file: str = "traces/factory_runs.jsonl"


class FactoryMemoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    enabled: bool = True
    namespace: str = "factory"


class FactoryTraceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    enabled: bool = True
    redact_secrets: bool = True


class FactoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    schema_version: str = "0.1"
    kind: Literal["FactoryConfig"] = "FactoryConfig"
    workspace_name: str = "FastAgentFactory"
    storage: FactoryStorageConfig = Field(default_factory=FactoryStorageConfig)
    memory: FactoryMemoryConfig = Field(default_factory=FactoryMemoryConfig)
    trace: FactoryTraceConfig = Field(default_factory=FactoryTraceConfig)

    @classmethod
    def default(cls, *, workspace_name: str = "FastAgentFactory") -> "FactoryConfig":
        return cls(workspace_name=workspace_name)

    @classmethod
    def load(cls, path: str | Path) -> "FactoryConfig":
        yaml = YAML(typ="safe")
        data = yaml.load(Path(path).read_text(encoding="utf-8")) or {}
        return cls.model_validate(data)

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        yaml = YAML()
        yaml.default_flow_style = False
        with target.open("w", encoding="utf-8") as handle:
            yaml.dump(self.model_dump(mode="json"), handle)
