from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.state import RuntimeState


class OperationalMemoryRetrieveNode:
    impl_id = "operational.memory_retrieve"
    node_type = "operational"
    supports_interrupt = False
    supports_subgraph_slot = True
    writable_sections = {"memory", "execution"}

    def execute(self, state: RuntimeState, context: NodeExecutionContext) -> dict[str, Any]:
        binding_payload = _first_binding_payload(context.bindings)
        engine = context.services.memory_engine
        items = engine.recall(state=state, binding=binding_payload) if engine is not None else []
        return {
            "memory": {
                "recall_items": items,
            },
            "execution": {"current_node": context.node_id, "route_decision": "always"},
        }


def _first_binding_payload(bindings: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not bindings:
        return None
    return dict(bindings[0].get("payload") or {})
