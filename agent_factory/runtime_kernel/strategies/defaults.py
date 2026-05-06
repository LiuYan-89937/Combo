from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from agent_factory.runtime_kernel.strategies.registry import StrategyExecutionContext, StrategyRegistry
from agent_factory.runtime_kernel.strategies.schema import StrategySpec


DEFAULT_MEMORY_RECALL_STRATEGY = StrategySpec(
    strategy_id="memory.recall.latest",
    kind="memory.recall",
    impl="memory.recall.latest",
    description="Recall the latest memory records for the current session.",
    config={"limit": 5},
)

DEFAULT_MEMORY_WRITE_STRATEGY = StrategySpec(
    strategy_id="memory.write.turn",
    kind="memory.write",
    impl="memory.write.turn",
    description="Persist the current user input and final answer as one memory record.",
    config={},
)


def default_strategy_registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register("memory.recall.latest", _memory_recall_latest)
    registry.register("memory.write.turn", _memory_write_turn)
    registry.register("memory.recall.none", _memory_recall_none)
    registry.register("memory.write.none", _memory_write_none)
    return registry


def _memory_recall_latest(strategy: StrategySpec, context: StrategyExecutionContext) -> list[dict[str, Any]]:
    store = _memory_store(context)
    state = context.state
    session_items = list(store.get(state.run.session_id, []))
    limit_value = strategy.config.get("limit")
    if limit_value is None:
        limit_value = (context.binding or {}).get("top_k", 5)
    limit = int(limit_value)
    state.memory.short_term_snapshot = {"count": len(session_items), "strategy_id": strategy.strategy_id}
    if limit <= 0:
        return []
    return session_items[-limit:]


def _memory_write_turn(strategy: StrategySpec, context: StrategyExecutionContext) -> list[dict[str, Any]]:
    store = _memory_store(context)
    state = context.state
    item = {
        "input": state.conversation.current_user_input,
        "answer": state.conversation.final_answer,
        "turn_index": state.conversation.turn_index,
        "strategy_id": strategy.strategy_id,
    }
    store.setdefault(state.run.session_id, []).append(item)
    return [item]


def _memory_recall_none(strategy: StrategySpec, context: StrategyExecutionContext) -> list[dict[str, Any]]:
    context.state.memory.short_term_snapshot = {"count": 0, "strategy_id": strategy.strategy_id}
    return []


def _memory_write_none(strategy: StrategySpec, context: StrategyExecutionContext) -> list[dict[str, Any]]:
    return []


def _memory_store(context: StrategyExecutionContext) -> MutableMapping[str, list[dict[str, Any]]]:
    store = context.resources.get("memory_store")
    if store is None:
        raise RuntimeError("Memory strategy requires a memory_store resource.")
    return store
