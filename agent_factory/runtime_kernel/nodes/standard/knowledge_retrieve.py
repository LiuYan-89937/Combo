from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.state import RuntimeState


class OperationalKnowledgeRetrieveNode:
    impl_id = "operational.knowledge_retrieve"
    node_type = "operational"
    supports_interrupt = False
    supports_subgraph_slot = True
    writable_sections = {"knowledge", "execution"}

    def execute(self, state: RuntimeState, context: NodeExecutionContext) -> dict[str, Any]:
        binding_payload = _first_binding_payload(context.bindings)
        query = (binding_payload or {}).get("query") or state.conversation.current_user_input or ""
        state.knowledge.retrieval_query = str(query)
        engine = context.services.knowledge_engine
        items = engine.retrieve(state=state, binding=binding_payload) if engine is not None else []
        ranked = items[: int((binding_payload or {}).get("top_k", 5))]
        return {
            "knowledge": {
                "retrieval_query": str(query),
                "retrieved_items": items,
                "ranked_items": ranked,
                "citations": [{"id": item.get("id"), "source": item.get("source")} for item in ranked],
            },
            "execution": {"current_node": context.node_id, "route_decision": "always"},
        }


def _first_binding_payload(bindings: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not bindings:
        return None
    return dict(bindings[0].get("payload") or {})
