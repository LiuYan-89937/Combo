from __future__ import annotations

from collections import defaultdict
from typing import Any

from agent_factory.runtime_kernel.state import RuntimeState
from agent_factory.runtime_kernel.strategies import (
    DEFAULT_MEMORY_RECALL_STRATEGY,
    DEFAULT_MEMORY_WRITE_STRATEGY,
    StrategyExecutionContext,
    StrategyRegistry,
    StrategySpec,
    default_strategy_registry,
    resolve_strategy_spec,
)


class InMemoryMemoryEngine:
    def __init__(
        self,
        *,
        strategies: list[StrategySpec | dict[str, Any]] | None = None,
        strategy_registry: StrategyRegistry | None = None,
    ) -> None:
        self._store: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.strategy_registry = strategy_registry or default_strategy_registry()
        self.strategy_specs = {
            strategy.strategy_id: strategy
            for strategy in (StrategySpec.model_validate(item) for item in (strategies or []))
        }

    def recall(self, *, state: RuntimeState, binding: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        strategy = resolve_strategy_spec(
            binding=binding,
            kind="memory.recall",
            default=DEFAULT_MEMORY_RECALL_STRATEGY,
            strategy_specs=self.strategy_specs,
            id_keys=("recall_strategy_id", "strategy_id"),
        )
        return self.strategy_registry.execute(
            strategy,
            StrategyExecutionContext(
                state=state,
                binding=binding,
                resources={"memory_store": self._store},
            ),
        )

    def write(self, *, state: RuntimeState, binding: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        strategy = resolve_strategy_spec(
            binding=binding,
            kind="memory.write",
            default=DEFAULT_MEMORY_WRITE_STRATEGY,
            strategy_specs=self.strategy_specs,
            id_keys=("write_strategy_id", "strategy_id"),
        )
        return self.strategy_registry.execute(
            strategy,
            StrategyExecutionContext(
                state=state,
                binding=binding,
                resources={"memory_store": self._store},
            ),
        )
