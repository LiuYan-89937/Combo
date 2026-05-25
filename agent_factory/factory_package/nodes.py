from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from agent_factory.factory_package.constants import MANUFACTURING_CLEARED_MESSAGE, MANUFACTURING_CLEARED_NODE_ID
from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.node_providers import StaticNodeProvider
from agent_factory.runtime_kernel.state import RuntimeState


FACTORY_MANUFACTURING_NAMESPACE = "factory_manufacturing"
FACTORY_NODE_PROVIDER_ID = "builtin.factory_manufacturing_nodes"


def factory_manufacturing_node_provider() -> StaticNodeProvider:
    return StaticNodeProvider(
        provider_id=FACTORY_NODE_PROVIDER_ID,
        nodes=(FactoryManufacturingClearedNode(),),
    )


@dataclass(frozen=True, slots=True)
class FactoryManufacturingClearedNode:
    node_type = "cognitive"
    supports_interrupt = False
    supports_subgraph_slot = False
    writable_sections = {"package_state", "conversation", "execution", "observability"}

    @property
    def impl_id(self) -> str:
        return f"builtin.factory.{MANUFACTURING_CLEARED_NODE_ID}"

    def execute(self, state: RuntimeState, _context: NodeExecutionContext) -> dict[str, Any]:
        namespace_state = _initial_state(state)
        record = {
            "version": "manufacturing_cleared.v0",
            "status": "cleared",
            "message": MANUFACTURING_CLEARED_MESSAGE,
        }
        next_state = {
            **namespace_state,
            "current_node": MANUFACTURING_CLEARED_NODE_ID,
            "status": "cleared",
            "manufacturing_cleared": record,
            "factory_response": {"message": MANUFACTURING_CLEARED_MESSAGE},
            "manufacturing_log": [
                *list(namespace_state.get("manufacturing_log") or []),
                {
                    "node_id": MANUFACTURING_CLEARED_NODE_ID,
                    "status": "cleared",
                    "message": MANUFACTURING_CLEARED_MESSAGE,
                },
            ],
        }
        return {
            "package_state": {FACTORY_MANUFACTURING_NAMESPACE: next_state},
            "conversation": {"final_answer": MANUFACTURING_CLEARED_MESSAGE},
            "execution": {
                "current_node": MANUFACTURING_CLEARED_NODE_ID,
                "finished": True,
                "finish_status": "completed",
                "route_decision": "execution.finished",
            },
        }


def _initial_state(state: RuntimeState) -> dict[str, Any]:
    existing = dict(state.package_state.get(FACTORY_MANUFACTURING_NAMESPACE) or {})
    if not existing.get("factory_run_id"):
        existing["factory_run_id"] = uuid4().hex
    current_input = (state.conversation.current_user_input or "").strip()
    if current_input and not existing.get("input_intent"):
        existing["input_intent"] = current_input
    if current_input and not existing.get("interaction_mode"):
        existing["interaction_mode"] = "create_agent"
    existing.setdefault("model_activity", [])
    existing.setdefault("manufacturing_log", [])
    existing.setdefault("errors", [])
    return existing
