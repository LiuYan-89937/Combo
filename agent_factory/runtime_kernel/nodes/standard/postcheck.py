from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.state import RuntimeState


class GovernancePostcheckNode:
    impl_id = "governance.postcheck"
    node_type = "governance"
    supports_interrupt = True
    supports_subgraph_slot = True
    writable_sections = {"policy", "conversation", "execution"}

    def execute(self, state: RuntimeState, context: NodeExecutionContext) -> dict[str, Any]:
        binding_payload = _first_binding_payload(context.bindings)
        engine = context.services.policy_engine
        if engine is None:
            return {"execution": {"current_node": context.node_id, "route_decision": "always"}}
        decision = engine.evaluate_postcheck(state=state, binding=binding_payload)
        context.emit_event({"event_type": "policy_checked", "phase": "postcheck", "decision": decision.status})
        if decision.status == "blocked":
            context.emit_event({"event_type": "policy_blocked", "phase": "postcheck", "reason": decision.reason})
            return {
                "policy": {
                    "blocked": True,
                    "refusal_reason": decision.reason,
                    "checks": [decision.model_dump(mode="json")],
                },
                "conversation": {
                    "final_answer": decision.reason or state.conversation.final_answer or "",
                },
                "execution": {
                    "current_node": context.node_id,
                    "route_decision": "policy.blocked",
                },
            }
        return {
            "policy": {"checks": [decision.model_dump(mode="json")]},
            "execution": {"current_node": context.node_id, "route_decision": "always"},
        }


def _first_binding_payload(bindings: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not bindings:
        return None
    return dict(bindings[0].get("payload") or {})
