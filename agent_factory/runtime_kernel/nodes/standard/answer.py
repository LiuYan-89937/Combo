from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from agent_factory.runtime_kernel.errors import RuntimeKernelError
from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.planning import PLAN_AND_EXECUTE_PATTERN_ID, RUNTIME_PLAN_TOOL_ID, runtime_plan_model_tool
from agent_factory.runtime_kernel.state import RuntimeState


class CognitiveAnswerNode:
    impl_id = "cognitive.answer"
    node_type = "cognitive"
    supports_interrupt = False
    supports_subgraph_slot = True
    writable_sections = {"conversation", "context", "tools", "execution"}

    def execute(
        self,
        state: RuntimeState,
        context: NodeExecutionContext,
    ) -> dict[str, Any]:
        binding_payload = _prompt_binding_payload(context)
        model_operation_service = context.services.model_operation_service
        if model_operation_service is None:
            raise RuntimeKernelError("cognitive.answer requires model_operation_service.")
        visible_tools = _visible_tools(context, state)
        result = model_operation_service.tool_bound_chat(
            state=state,
            prompt_binding=binding_payload,
            messages=context.graph_messages,
            tools=visible_tools,
            emit_event=context.emit_event,
            services=context.services,
            node_id=context.node_id,
        )
        if result.clarification_question:
            return {
                "messages": [AIMessage(content=result.clarification_question)],
                **_context_token_budget_patch(result.metadata, context.node_id),
                "conversation": {
                    "assistant_draft": result.assistant_draft,
                    "clarification_question": result.clarification_question,
                },
                "execution": {
                    "current_node": context.node_id,
                    "route_decision": result.route_decision or "subgraph.need_more_input",
                },
            }
        ai_message = result.ai_message if isinstance(result.ai_message, AIMessage) else None
        tool_calls = _message_tool_calls(ai_message) or list(result.tool_calls or [])
        if tool_calls:
            tool_calls = [_with_origin(call, context) for call in tool_calls]
            return {
                "messages": [_ai_message_with_origin(result.assistant_draft or "", tool_calls, context)],
                **_context_token_budget_patch(result.metadata, context.node_id),
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
        response_message = AIMessage(content=final_answer)
        return {
            "messages": [response_message],
            **_context_token_budget_patch(result.metadata, context.node_id),
            "conversation": {
                "assistant_draft": result.assistant_draft,
                "final_answer": final_answer,
            },
            "execution": {
                "current_node": context.node_id,
                "route_decision": result.route_decision or "model.ready_to_answer",
            },
        }


def _prompt_binding_payload(context: NodeExecutionContext) -> dict[str, Any] | None:
    model_operation = _model_operation_payload(context.bindings)
    prompt_id = str(model_operation.get("prompt_id") or "").strip()
    if prompt_id:
        return _prompt_binding_by_id(context, prompt_id)
    for binding in context.bindings:
        if binding.get("binding_type") == "prompt":
            return dict(binding.get("payload") or {})
    return None


def _model_operation_payload(bindings: list[dict[str, Any]]) -> dict[str, Any]:
    for binding in bindings:
        if binding.get("binding_type") == "model_operation":
            return dict(binding.get("payload") or {})
    return {}


def _prompt_binding_by_id(context: NodeExecutionContext, prompt_id: str) -> dict[str, Any] | None:
    for binding in context.bindings:
        if binding.get("binding_type") != "prompt":
            continue
        payload = dict(binding.get("payload") or {})
        if payload.get("prompt_id") == prompt_id:
            return payload
    for binding in context.all_bindings:
        if binding.get("binding_type") != "prompt":
            continue
        target = dict(binding.get("target") or {})
        if target.get("node_id") != context.node_id or target.get("impl") != context.impl:
            continue
        payload = dict(binding.get("payload") or {})
        if payload.get("prompt_id") == prompt_id:
            return payload
    raise RuntimeKernelError(f"cognitive.answer prompt binding not found: {prompt_id}")


def _context_token_budget_patch(metadata: dict[str, Any] | None, node_id: str) -> dict[str, Any]:
    data = dict(metadata or {})
    input_tokens = data.get("provider_input_tokens")
    if not isinstance(input_tokens, int) and not isinstance(input_tokens, float):
        return {}
    usage_metadata = data.get("usage_metadata") if isinstance(data.get("usage_metadata"), dict) else {}
    return {
        "context": {
            "token_budget": {
                "last_provider_input_tokens": int(input_tokens),
                "last_provider_token_count_method": "provider_usage",
                "last_provider_node_id": node_id,
                "last_provider_model_role": str(data.get("model_role") or ""),
                "last_provider_usage_metadata": usage_metadata,
            }
        }
    }


def _message_tool_calls(message: AIMessage | None) -> list[dict[str, Any]]:
    if message is None:
        return []
    calls = getattr(message, "tool_calls", None) or []
    return [dict(item) for item in calls if isinstance(item, dict)]


def _visible_tools(context: NodeExecutionContext, state: RuntimeState) -> list[Any]:
    registry = context.services.tool_registry
    allowed_tool_ids = _model_visible_tool_ids(context, state, registry)
    tools: list[Any] = []
    if registry is None or not hasattr(registry, "model_tools"):
        registry_tools = []
    else:
        registry_tools = list(registry.model_tools(allowed_tool_ids))
    tools.extend(registry_tools)
    if _runtime_plan_visible(context=context, state=state, allowed_tool_ids=allowed_tool_ids):
        tools.append(runtime_plan_model_tool())
    return tools


def _model_visible_tool_ids(context: NodeExecutionContext, state: RuntimeState, registry: Any) -> list[str]:
    if _is_plan_and_execute_node(context, state):
        return _tool_access_ids(context.bindings)
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


def _runtime_plan_visible(*, context: NodeExecutionContext, state: RuntimeState, allowed_tool_ids: list[str]) -> bool:
    if state.run.pattern_id != PLAN_AND_EXECUTE_PATTERN_ID:
        return False
    if context.node_id not in {"planner", "executor"}:
        return False
    return RUNTIME_PLAN_TOOL_ID in set(allowed_tool_ids)


def _is_plan_and_execute_node(context: NodeExecutionContext, state: RuntimeState) -> bool:
    if state.run.pattern_id != PLAN_AND_EXECUTE_PATTERN_ID:
        return False
    return context.node_id in {"planner", "executor", "final_answer"}


def _with_origin(call: dict[str, Any], context: NodeExecutionContext) -> dict[str, Any]:
    return {
        **dict(call),
        "origin_node_id": context.node_id,
        "origin_impl": context.impl,
    }


def _ai_message_with_origin(content: str, tool_calls: list[dict[str, Any]], context: NodeExecutionContext) -> AIMessage:
    return AIMessage(
        content=content,
        tool_calls=tool_calls,
        additional_kwargs={
            "agent_factory_origin_node_id": context.node_id,
            "agent_factory_origin_impl": context.impl,
        },
    )
