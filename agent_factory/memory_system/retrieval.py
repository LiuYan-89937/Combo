from __future__ import annotations

from time import perf_counter

from langgraph.store.base import BaseStore, SearchItem

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
    semantic_items, semantic_error = _search_with_query(
        store=store,
        namespace=namespace,
        query=query,
        limit=max(config.ranking.max_items_total * 4, 16),
    )
    lexical_items, lexical_error = _search_without_query(
        store=store,
        namespace=namespace,
        limit=max(config.ranking.max_items_total * 8, 32),
    )
    raw_items = _merge_search_items([*semantic_items, *lexical_items])
    ranked, token_estimate = rank_memory_items(items=raw_items, query=query, config=config.ranking)
    return MemoryContextPack(
        namespace=namespace,
        query=query,
        items=ranked,
        token_estimate=token_estimate,
        report={
            "status": "completed",
            "raw_count": len(raw_items),
            "semantic_count": len(semantic_items),
            "lexical_count": len(lexical_items),
            "selected_count": len(ranked),
            "semantic_error": semantic_error,
            "lexical_error": lexical_error,
            "duration_ms": int((perf_counter() - started) * 1000),
        },
    )


def _search_with_query(
    *,
    store: BaseStore,
    namespace: tuple[str, ...],
    query: str,
    limit: int,
) -> tuple[list[SearchItem], str | None]:
    if not query.strip():
        return [], None
    try:
        return store.search(namespace, query=query, limit=limit), None
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"


def _search_without_query(
    *,
    store: BaseStore,
    namespace: tuple[str, ...],
    limit: int,
) -> tuple[list[SearchItem], str | None]:
    try:
        return store.search(namespace, query=None, limit=limit), None
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"


def _merge_search_items(items: list[SearchItem]) -> list[SearchItem]:
    merged: dict[tuple[tuple[str, ...], str], SearchItem] = {}
    for item in items:
        key = (tuple(item.namespace), item.key)
        existing = merged.get(key)
        if existing is None or _score_value(item) > _score_value(existing):
            merged[key] = item
    return list(merged.values())


def _score_value(item: SearchItem) -> float:
    score = getattr(item, "score", None)
    try:
        return float(score)
    except (TypeError, ValueError):
        return -1.0
