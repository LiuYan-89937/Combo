from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML

from agent_factory.runtime_kernel.patterns.schema import GraphPatternSpec


class PatternLoader:
    def __init__(self) -> None:
        self._yaml = YAML(typ="safe")

    def load_path(self, path: str | Path) -> GraphPatternSpec:
        data = self._yaml.load(Path(path).read_text(encoding="utf-8")) or {}
        return GraphPatternSpec.model_validate(data)
