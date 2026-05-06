from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.state import RuntimeState


class GovernanceApprovalGateNode:
    impl_id = "governance.approval_gate"
    node_type = "governance"
    supports_interrupt = True
    supports_subgraph_slot = True
    writable_sections = {"policy", "execution"}

    def execute(self, state: RuntimeState, context: NodeExecutionContext) -> dict[str, Any]:
        if state.policy.approval_required or state.policy.interrupt_required:
            return {
                "policy": {
                    "interrupted": True,
                    "interrupt_required": True,
                    "interrupt_type": state.policy.interrupt_type or "approval_required",
                },
                "execution": {
                    "current_node": context.node_id,
                    "interrupted": True,
                    "route_decision": "policy.approval_required",
                },
            }
        return {
            "execution": {
                "current_node": context.node_id,
                "route_decision": "always",
            }
        }
