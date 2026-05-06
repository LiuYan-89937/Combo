from __future__ import annotations

from uuid import uuid4

from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.state import RuntimeState


class IngressNode:
    impl_id = "ingress"
    node_type = "reserved"
    supports_interrupt = False
    supports_subgraph_slot = False
    writable_sections = {"conversation", "execution"}

    def execute(
        self,
        state: RuntimeState,
        context: NodeExecutionContext,
    ) -> dict[str, object]:
        messages = list(state.conversation.messages)
        if state.conversation.current_user_input:
            messages.append(
                {
                    "role": "user",
                    "content": state.conversation.current_user_input,
                    "name": None,
                    "tool_call_id": None,
                    "tool_calls": [],
                    "additional_kwargs": {},
                }
            )
        return {
            "conversation": {
                "messages": messages,
                "current_user_input_id": state.conversation.current_user_input_id or uuid4().hex,
                "turn_index": state.conversation.turn_index + 1,
            },
            "execution": {
                "current_node": context.node_id,
            },
        }
