from __future__ import annotations

from time import perf_counter

from langgraph.store.base import BaseStore

from agent_factory.memory_system.config import MemorySystemConfig
from agent_factory.memory_system.ranking import rank_memory_items
from agent_factory.memory_system.schema import MemoryContextPack


def retrieve_memory_context(
    *,
    store: BaseStore | None,
    namespace: tuple[str, ...],
    query: str,
    config: MemorySystemConfig,
) -> MemoryContextPack:
    started = perf_counter()
    if store is None or not config.enabled or not config.injection_enabled:
        return MemoryContextPack(
            namespace=namespace,
            query=query,
            report={"status": "skipped", "reason": "memory disabled or store missing"},
        )
    raw_items = store.search(namespace, query=query or None, limit=max(config.ranking.max_items_total * 4, 16))
    ranked, token_estimate = rank_memory_items(items=raw_items, query=query, config=config.ranking)
    return MemoryContextPack(
        namespace=namespace,
        query=query,
        items=ranked,
        token_estimate=token_estimate,
        report={
            "status": "completed",
            "raw_count": len(raw_items),
            "selected_count": len(ranked),
            "duration_ms": int((perf_counter() - started) * 1000),
        },
    )
