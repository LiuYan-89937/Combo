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
    semantic_report_before = _semantic_index_report(store)
    semantic_items, semantic_error = _search_with_query(
        store=store,
        namespace=namespace,
        query=query,
        limit=max(config.ranking.max_items_total * 4, 16),
    )
    semantic_report_after = _semantic_index_report(store)
    lexical_items, lexical_error = _search_without_query(
        store=store,
        namespace=namespace,
        limit=max(config.ranking.max_items_total * 8, 32),
    )
    raw_items = _merge_search_items([*semantic_items, *lexical_items])
    ranked, token_estimate = rank_memory_items(items=raw_items, query=query, config=config.ranking)
    semantic_status = _semantic_status(
        semantic_error=semantic_error,
        semantic_items=semantic_items,
        report_before=semantic_report_before,
        report_after=semantic_report_after,
    )
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
            "semantic_status": semantic_status,
            "semantic_error": semantic_error,
            "lexical_error": lexical_error,
            "lexical_fallback_used": semantic_status in {"semantic_failed", "semantic_unavailable"} and bool(lexical_items),
            "semantic_diagnostics": _recent_semantic_diagnostics(semantic_report_after),
            "semantic_query_diagnostic": _latest_semantic_diagnostic(semantic_report_after, operation="query_embedding"),
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


def _semantic_index_report(store: BaseStore) -> dict:
    reporter = getattr(store, "semantic_index_report", None)
    if not callable(reporter):
        return {"enabled": None, "diagnostics": []}
    try:
        report = reporter()
    except Exception as exc:
        return {
            "enabled": None,
            "diagnostics": [
                {
                    "operation": "semantic_index_report",
                    "status": "failed",
                    "reason": "report_error",
                    "message": f"{type(exc).__name__}: {exc}",
                }
            ],
        }
    return report if isinstance(report, dict) else {"enabled": None, "diagnostics": []}


def _semantic_status(
    *,
    semantic_error: str | None,
    semantic_items: list[SearchItem],
    report_before: dict,
    report_after: dict,
) -> str:
    if semantic_error:
        return "semantic_failed"
    latest_query = _latest_semantic_diagnostic(report_after, operation="query_embedding")
    if latest_query:
        status = str(latest_query.get("status") or "")
        if status == "ok":
            return "semantic_available"
        if status == "failed":
            return "semantic_failed"
        if status == "unavailable":
            return "semantic_unavailable"
    if report_after.get("enabled") is False:
        return "semantic_unavailable"
    if semantic_items and report_after.get("enabled") is not False:
        return "semantic_available"
    if _recent_semantic_diagnostics(report_after) != _recent_semantic_diagnostics(report_before):
        return "semantic_failed"
    return "semantic_unavailable"


def _recent_semantic_diagnostics(report: dict) -> list[dict]:
    diagnostics = report.get("diagnostics")
    if not isinstance(diagnostics, list):
        return []
    return [item for item in diagnostics[-5:] if isinstance(item, dict)]


def _latest_semantic_diagnostic(report: dict, *, operation: str) -> dict | None:
    for item in reversed(_recent_semantic_diagnostics(report)):
        if str(item.get("operation") or "") == operation:
            return item
    return None
