from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.state import RuntimeState


class KnowledgeEngine:
    def __init__(self, documents: list[dict[str, Any]] | None = None) -> None:
        self.documents = list(
            documents
            or [
                {"id": "doc_orders", "text": "订单查询支持按 id 和关键词搜索。", "source": "builtin"},
                {"id": "doc_policy", "text": "高风险写操作必须审批。", "source": "builtin"},
            ]
        )

    def retrieve(self, *, state: RuntimeState, binding: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        query = (state.knowledge.retrieval_query or state.conversation.current_user_input or "").strip()
        if not query:
            return []
        words = {item for item in query.lower().split() if item}
        if not words:
            return []
        scored: list[tuple[int, dict[str, Any]]] = []
        for document in self.documents:
            text = str(document.get("text") or "").lower()
            score = sum(1 for word in words if word in text)
            if score:
                scored.append((score, document))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item for _score, item in scored[:5]]
