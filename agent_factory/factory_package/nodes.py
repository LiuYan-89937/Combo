from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_factory.factory_package.constants import (
    CREATE_AGENT_ENTRY_NODE_ID,
    CREATE_AGENT_NODE_PROVIDER_ID,
    CREATE_AGENT_STATE_NAMESPACE,
)
from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.node_providers import StaticNodeProvider
from agent_factory.runtime_kernel.state import RuntimeState


def factory_create_agent_entry_node_provider() -> StaticNodeProvider:
    return StaticNodeProvider(
        provider_id=CREATE_AGENT_NODE_PROVIDER_ID,
        nodes=(CreateAgentEntryNode(),),
    )


@dataclass(frozen=True, slots=True)
class CreateAgentEntryNode:
    node_type = "terminal"
    supports_interrupt = False
    supports_subgraph_slot = False
    writable_sections = {"package_state", "conversation", "execution"}

    @property
    def impl_id(self) -> str:
        return f"builtin.factory.{CREATE_AGENT_ENTRY_NODE_ID}"

    def execute(self, state: RuntimeState, _context: NodeExecutionContext) -> dict[str, Any]:
        user_input = state.conversation.current_user_input or ""
        message = (
            "create-agent 后端制造实现已清空。CLI 入口保留，新的制造流程等待重新设计后接入。"
        )
        next_state = {
            "status": "cleared",
            "input_intent": user_input,
            "message": message,
        }
        return {
            "package_state": {CREATE_AGENT_STATE_NAMESPACE: next_state},
            "conversation": {"final_answer": message},
            "execution": {
                "current_node": CREATE_AGENT_ENTRY_NODE_ID,
                "finished": True,
                "finish_status": "completed",
                "route_decision": "execution.finished",
            },
        }
