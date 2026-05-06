from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.state import RuntimeState


class GovernancePrecheckNode:
    impl_id = "governance.precheck"
    node_type = "governance"
    supports_interrupt = True
    supports_subgraph_slot = True
    writable_sections = {"policy", "execution"}

    def execute(
        self,
        state: RuntimeState,
        context: NodeExecutionContext,
    ) -> dict[str, Any]:
        binding_payload = _first_binding_payload(context.bindings)
        engine = context.services.policy_engine
        if engine is None:
            return {"execution": {"current_node": context.node_id, "route_decision": "always"}}
        decision = engine.evaluate_precheck(state=state, binding=binding_payload)
        context.emit_event({"event_type": "policy_checked", "phase": "precheck", "decision": decision.status})
        if decision.status == "blocked":
            context.emit_event({"event_type": "policy_blocked", "phase": "precheck", "reason": decision.reason})
            return {
                "policy": {
                    "blocked": True,
                    "block_reason": decision.reason,
                    "checks": [decision.model_dump(mode="json")],
                },
                "execution": {
                    "current_node": context.node_id,
                    "route_decision": "policy.blocked",
                },
            }
        if decision.status == "interrupted":
            context.emit_event({"event_type": "interrupt_triggered", "phase": "precheck", "reason": decision.reason})
            return {
                "policy": {
                    "approval_required": decision.approval_required,
                    "interrupt_required": decision.interrupt_required or decision.approval_required,
                    "interrupted": True,
                    "interrupt_type": decision.interrupt_type or "approval_required",
                    "checks": [decision.model_dump(mode="json")],
                },
                "execution": {
                    "current_node": context.node_id,
                    "interrupted": True,
                    "route_decision": "policy.approval_required",
                },
            }
        return {
            "policy": {
                "checks": [decision.model_dump(mode="json")],
            },
            "execution": {
                "current_node": context.node_id,
                "route_decision": "always",
            },
        }


def _first_binding_payload(bindings: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not bindings:
        return None
    return dict(bindings[0].get("payload") or {})
