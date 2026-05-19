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
        visible_tools = _visible_tools(context)
        result = model_service.generate(
            state=state,
            prompt_binding=binding_payload,
            messages=context.graph_messages,
            tools=visible_tools,
        )
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
        tool_calls = result.tool_calls
        if tool_calls:
            ai_message = result.ai_message if isinstance(result.ai_message, AIMessage) else None
            first_call = tool_calls[0]
            tool_id = str(first_call.get("name") or "")
            tool_call_id = str(first_call.get("id") or tool_id)
            arguments = dict(first_call.get("args") or {})
            context.emit_event(
                {
                    "event_type": "tool_proposed",
                    "tool_id": tool_id,
                    "tool_call_id": tool_call_id,
                    "arguments": arguments,
                }
            )
            return {
                "messages": [ai_message or AIMessage(content=result.assistant_draft or "", tool_calls=tool_calls)],
                "conversation": {
                    "assistant_draft": result.assistant_draft,
                },
                "tools": {
                    "pending_tool_call": None,
                    "pending_tool_calls": [],
                },
                "execution": {
                    "current_node": context.node_id,
                    "route_decision": "model.requests_tool",
                },
            }
        final_answer = result.final_answer or result.assistant_draft or ""
        ai_message = result.ai_message if isinstance(result.ai_message, AIMessage) else None
        return {
            "messages": [ai_message or AIMessage(content=final_answer)],
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


def _visible_tools(context: NodeExecutionContext) -> list[Any]:
    registry = context.services.tool_registry
    if registry is None or not hasattr(registry, "model_tools"):
        return []
    allowed_tool_ids = _model_visible_tool_ids(context, registry)
    return list(registry.model_tools(allowed_tool_ids))


def _model_visible_tool_ids(context: NodeExecutionContext, registry: Any) -> list[str]:
    return _merge_tool_ids([*_allowed_tool_ids(context), *_system_tool_ids(registry)])


def _system_tool_ids(registry: Any) -> list[str]:
    if not hasattr(registry, "system_tool_ids"):
        return []
    return [str(item) for item in registry.system_tool_ids()]


def _allowed_tool_ids(context: NodeExecutionContext) -> list[str]:
    current_node_tool_ids = _tool_access_ids(context.bindings)
    if current_node_tool_ids:
        return current_node_tool_ids
    return _tool_access_ids(context.all_bindings)


def _tool_access_ids(bindings: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for binding in bindings:
        if binding.get("binding_type") != "tool_access":
            continue
        payload = dict(binding.get("payload") or {})
        for item in payload.get("allowed_tool_ids", []) or []:
            tool_id = str(item)
            if tool_id and tool_id not in seen:
                ids.append(tool_id)
                seen.add(tool_id)
    return ids


def _merge_tool_ids(tool_ids: list[str]) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for tool_id in tool_ids:
        item = str(tool_id).strip()
        if item and item not in seen:
            items.append(item)
            seen.add(item)
    return items
