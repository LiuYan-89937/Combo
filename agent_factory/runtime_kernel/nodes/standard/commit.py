from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.state import RuntimeState


class TerminalCommitNode:
    impl_id = "terminal.commit"
    node_type = "terminal"
    supports_interrupt = False
    supports_subgraph_slot = False
    writable_sections = {"memory", "execution"}

    def execute(self, state: RuntimeState, context: NodeExecutionContext) -> dict[str, Any]:
        binding_payload = _first_binding_payload(context.bindings)
        engine = context.services.memory_engine
        written = engine.write(state=state, binding=binding_payload) if engine is not None else []
        return {
            "memory": {
                "pending_write": written,
                "write_applied": True,
            },
            "execution": {"current_node": context.node_id, "route_decision": "always"},
        }


def _first_binding_payload(bindings: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not bindings:
        return None
    return dict(bindings[0].get("payload") or {})
