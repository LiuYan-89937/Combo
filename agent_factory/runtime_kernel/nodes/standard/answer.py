from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from agent_factory.runtime_kernel.errors import RuntimeKernelError
from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.plan_execute_tools import (
    PLAN_EXECUTE_NODE_IDS,
    available_tool_ids,
    plan_and_execute_model_tool_ids,
    without_runtime_plan,
)
from agent_factory.runtime_kernel.planning import RUNTIME_PLAN_TOOL_ID, runtime_plan_model_tool
from agent_factory.runtime_kernel.state import RuntimeState
from agent_factory.context_system.token_counter import provider_token_budget_payload
from agent_factory.runtime_kernel.tool_governance import exhausted_tool_ids


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
        model_operation_service = context.services.model_operation_service
        if model_operation_service is None:
            raise RuntimeKernelError("cognitive.answer requires model_operation_service.")
        visible_tools = _visible_tools(context, state)
        result = model_operation_service.tool_bound_chat(
            state=state,
            messages=context.graph_messages,
            tools=visible_tools,
            emit_event=context.emit_event,
            services=context.services,
            node_id=context.node_id,
        )
        if result.clarification_question:
            reasoning_content = _reasoning_content_from_metadata(result.metadata)
            return {
                "messages": [AIMessage(content=result.clarification_question)],
                **_context_token_budget_patch(result.metadata, context.node_id),
                "conversation": {
                    "assistant_draft": result.assistant_draft,
                    "reasoning_content": reasoning_content,
                    "clarification_question": result.clarification_question,
                },
                "execution": {
                    "current_node": context.node_id,
                    "route_decision": result.route_decision or "subgraph.need_more_input",
                },
            }
        ai_message = result.ai_message if isinstance(result.ai_message, AIMessage) else None
        tool_calls = _message_tool_calls(ai_message) or list(result.tool_calls or [])
        reasoning_content = _reasoning_content_from_metadata(result.metadata)
        if tool_calls:
            _emit_activity_summary(context, result.assistant_draft)
            return {
                "messages": [
                    _ai_message_with_origin(
                        result.assistant_draft or "",
                        tool_calls,
                        context,
                        reasoning_content=reasoning_content,
                    )
                ],
                **_context_token_budget_patch(result.metadata, context.node_id),
                "conversation": {
                    "assistant_draft": result.assistant_draft,
                    "reasoning_content": reasoning_content,
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
        response_message = AIMessage(
            content=final_answer,
            additional_kwargs=(
                {"reasoning_content": reasoning_content}
                if reasoning_content
                else {}
            ),
        )
        route_decision = result.route_decision or "model.ready_to_answer"
        if _plan_and_execute_planner_waiting_for_input(context=context, state=state):
            route_decision = "subgraph.need_more_input"
        return {
            "messages": [response_message],
            **_context_token_budget_patch(result.metadata, context.node_id),
            "conversation": {
                "assistant_draft": result.assistant_draft,
                "reasoning_content": reasoning_content,
                "final_answer": final_answer,
            },
            "execution": {
                "current_node": context.node_id,
                "route_decision": route_decision,
            },
        }


def _context_token_budget_patch(metadata: dict[str, Any] | None, node_id: str) -> dict[str, Any]:
    data = dict(metadata or {})
    usage_metadata = data.get("usage_metadata") if isinstance(data.get("usage_metadata"), dict) else {}
    usage_observation = (
        data.get("usage_observation")
        if isinstance(data.get("usage_observation"), dict)
        else {}
    )
    token_budget = provider_token_budget_payload(
        usage_metadata=usage_metadata,
        provider_input_tokens=usage_observation.get("input_tokens"),
        fallback_output_tokens=usage_observation.get("output_tokens"),
        usage_source=str(usage_observation.get("usage_source") or "local_estimation"),
        node_id=node_id,
        model_role=str(data.get("model_role") or ""),
    )
    if not token_budget:
        return {}
    return {
        "context": {
            "token_budget": token_budget,
        }
    }


def _message_tool_calls(message: AIMessage | None) -> list[dict[str, Any]]:
    if message is None:
        return []
    calls = getattr(message, "tool_calls", None) or []
    return [dict(item) for item in calls if isinstance(item, dict)]


def _visible_tools(context: NodeExecutionContext, state: RuntimeState) -> list[Any]:
    registry = context.services.tool_registry
    if registry is None or not hasattr(registry, "model_tools"):
        raise RuntimeKernelError("cognitive.answer requires a snapshot-bound tool registry.")
    allowed_tool_ids = _model_visible_tool_ids(context, state)
    tools: list[Any] = list(registry.model_tools(without_runtime_plan(allowed_tool_ids)))
    if _runtime_plan_visible(context=context, state=state, allowed_tool_ids=allowed_tool_ids):
        tools.append(runtime_plan_model_tool())
    return tools


def _model_visible_tool_ids(context: NodeExecutionContext, state: RuntimeState) -> list[str]:
    if _is_plan_and_execute_node(context, state):
        visible_tool_ids = plan_and_execute_model_tool_ids(
            node_id=context.node_id,
            state=state,
        )
    else:
        visible_tool_ids = available_tool_ids(state)
    unavailable_tool_ids = exhausted_tool_ids(state)
    return [tool_id for tool_id in visible_tool_ids if tool_id not in unavailable_tool_ids]


def _runtime_plan_visible(*, context: NodeExecutionContext, state: RuntimeState, allowed_tool_ids: list[str]) -> bool:
    if state.run.strategy != "plan_and_execute":
        return False
    if context.node_id not in {"planner", "executor"}:
        return False
    return RUNTIME_PLAN_TOOL_ID in set(allowed_tool_ids)


def _is_plan_and_execute_node(context: NodeExecutionContext, state: RuntimeState) -> bool:
    if state.run.strategy != "plan_and_execute":
        return False
    return context.node_id in PLAN_EXECUTE_NODE_IDS


def _plan_and_execute_planner_waiting_for_input(*, context: NodeExecutionContext, state: RuntimeState) -> bool:
    if state.run.strategy != "plan_and_execute":
        return False
    if context.node_id != "planner":
        return False
    return getattr(state.plan, "status", "empty") == "empty"


def _reasoning_content_from_metadata(metadata: dict[str, Any] | None) -> str | None:
    value = (metadata or {}).get("reasoning_content")
    if isinstance(value, str):
        return value.strip() or None
    return None


def _emit_activity_summary(context: NodeExecutionContext, value: str | None) -> None:
    summary = _activity_summary(value)
    if not summary:
        return
    context.emit_event(
        {
            "event_type": "runtime_activity_updated",
            "summary": summary,
            "status": "active",
            "source": "model",
        }
    )


def _activity_summary(value: str | None) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    return text[:240].rstrip()


def _ai_message_with_origin(
    content: str,
    tool_calls: list[dict[str, Any]],
    context: NodeExecutionContext,
    *,
    reasoning_content: str | None = None,
) -> AIMessage:
    additional_kwargs = {
        "agent_factory_origin_node_id": context.node_id,
        "agent_factory_origin_impl": context.impl,
    }
    if reasoning_content:
        additional_kwargs["reasoning_content"] = reasoning_content
    return AIMessage(
        content=content,
        tool_calls=tool_calls,
        additional_kwargs=additional_kwargs,
    )
