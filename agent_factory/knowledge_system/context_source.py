from __future__ import annotations

from agent_factory.context_system.compression import estimate_text_tokens
from agent_factory.context_system.schema import ContextCandidate, ContextQuery
from agent_factory.context_system.sources import ContextSourceRuntime
from agent_factory.knowledge_system.runtime import KnowledgeRuntime


class KnowledgeContextSource:
    source_id = "knowledge"

    def __init__(self, runtime: KnowledgeRuntime) -> None:
        self.runtime = runtime

    def retrieve(self, *, query: ContextQuery, runtime_context: ContextSourceRuntime) -> list[ContextCandidate]:
        selected = dict(getattr(getattr(runtime_context.state, "context", None), "model_context", {}) or {}).get(
            "selected_knowledge_results"
        )
        if isinstance(selected, list) and selected:
            return [_candidate_from_result(item) for item in selected if isinstance(item, dict)]
        return []


def _candidate_from_result(item: dict) -> ContextCandidate:
    content = str(item.get("content") or "")
    return ContextCandidate(
        candidate_id=str(item.get("result_id") or item.get("chunk_id") or "knowledge"),
        source_id="knowledge",
        kind="knowledge",
        content=content,
        score=float(item.get("score") or 0.8),
        token_estimate=estimate_text_tokens(content),
        metadata={
            "source_id": item.get("source_id"),
            "document_id": item.get("document_id"),
            "chunk_id": item.get("chunk_id"),
            "title": item.get("title"),
        },
    )
