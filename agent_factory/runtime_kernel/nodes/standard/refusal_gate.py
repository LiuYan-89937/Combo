from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.state import RuntimeState


class GovernanceRefusalGateNode:
    impl_id = "governance.refusal_gate"
    node_type = "governance"
    supports_interrupt = False
    supports_subgraph_slot = True
    writable_sections = {"conversation", "execution"}

    def execute(self, state: RuntimeState, context: NodeExecutionContext) -> dict[str, Any]:
        answer = state.policy.refusal_reason or state.conversation.final_answer or state.conversation.assistant_draft or ""
        return {
            "conversation": {"final_answer": answer},
            "execution": {"current_node": context.node_id, "route_decision": "always"},
        }
