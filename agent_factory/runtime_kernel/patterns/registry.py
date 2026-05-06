from __future__ import annotations

from pathlib import Path

from agent_factory.runtime_kernel.errors import RuntimeKernelError
from agent_factory.runtime_kernel.patterns.loader import PatternLoader
from agent_factory.runtime_kernel.patterns.schema import GraphPatternSpec
from agent_factory.runtime_kernel.patterns.validator import PatternValidator


class PatternRegistry:
    def __init__(
        self,
        *,
        builtins_dir: str | Path | None = None,
        loader: PatternLoader | None = None,
        validator: PatternValidator | None = None,
    ) -> None:
        self.loader = loader or PatternLoader()
        self.validator = validator or PatternValidator()
        self._patterns: dict[str, GraphPatternSpec] = {}
        if builtins_dir is not None:
            self.load_builtins(builtins_dir)

    def load_builtins(self, builtins_dir: str | Path) -> None:
        root = Path(builtins_dir)
        raw_patterns = [self.loader.load_path(path) for path in sorted(root.glob("*.yaml"))]
        known_ids = {pattern.pattern_id for pattern in raw_patterns}
        self._patterns = {
            pattern.pattern_id: self.validator.validate(pattern, known_patterns=known_ids)
            for pattern in raw_patterns
        }

    def get(self, pattern_id: str) -> GraphPatternSpec:
        if pattern_id not in self._patterns:
            raise RuntimeKernelError(f"Unknown pattern: {pattern_id}")
        return self._patterns[pattern_id]

    def list_pattern_ids(self) -> list[str]:
        return sorted(self._patterns)
