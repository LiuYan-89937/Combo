from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict
from ruamel.yaml import YAML


class FactoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    workspace_name: str = "FastAgentFactory"
    trace_file: str = "traces/factory_runs.jsonl"

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
