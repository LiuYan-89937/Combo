from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from agent_factory.runtime_kernel.errors import RuntimeKernelError
from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.state import RuntimeState


class CognitiveAnswerNode:
    impl_id = "cognitive.answer"
    node_type = "cognitive"
    supports_interrupt = False
    supports_subgraph_slot = True
    writable_sections = {"conversation", "tools", "execution"}

    def execute(
        self,
        state: RuntimeState,
        context: NodeExecutionContext,
    ) -> dict[str, Any]:
        binding_payload = _first_binding_payload(context.bindings)
        model_service = context.services.model_service
        if model_service is None:
            raise RuntimeKernelError("cognitive.answer requires model_service.")
        result = model_service.generate(state=state, prompt_binding=binding_payload)
        if result.clarification_question:
            return {
                "messages": [AIMessage(content=result.clarification_question)],
                "conversation": {
                    "assistant_draft": result.assistant_draft,
                    "clarification_question": result.clarification_question,
                },
                "execution": {
                    "current_node": context.node_id,
                    "route_decision": result.route_decision or "subgraph.need_more_input",
                },
            }
        if result.requests_tool and result.tool_name:
            context.emit_event(
                {
                    "event_type": "tool_proposed",
                    "tool_id": result.tool_name,
                    "arguments": dict(result.tool_arguments),
                }
            )
            return {
                "messages": [AIMessage(content=result.assistant_draft or "")],
                "conversation": {
                    "assistant_draft": result.assistant_draft,
                },
                "tools": {
                    "pending_tool_call": {
                        "tool_id": result.tool_name,
                        "arguments": dict(result.tool_arguments),
                    },
                },
                "execution": {
                    "current_node": context.node_id,
                    "route_decision": "model.requests_tool",
                },
            }
        final_answer = result.final_answer or result.assistant_draft or ""
        return {
            "messages": [AIMessage(content=final_answer)],
            "conversation": {
                "assistant_draft": result.assistant_draft,
                "final_answer": final_answer,
            },
            "execution": {
                "current_node": context.node_id,
                "route_decision": result.route_decision or "model.ready_to_answer",
            },
        }


def _first_binding_payload(bindings: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not bindings:
        return None
    return dict(bindings[0].get("payload") or {})
