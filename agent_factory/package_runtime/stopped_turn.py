from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from agent_factory.factory_graph.frontend_bridge.event_normalizer import VisibleAssistantMessage
from agent_factory.runtime_kernel.state import RuntimeState
from agent_factory.runtime_protocol.messages import close_incomplete_tool_call_history


LANGGRAPH_INPUT_NODE = "__input__"
USER_STOP_MARKER_CONTENT = (
    "用户已停止上一条助手回复。请将上一条助手回复视为已被用户中断，等待并遵循下一条用户消息继续。"
)
USER_STEER_MARKER_CONTENT = (
    "用户用新的引导中断了上一条助手回复。上一条回复和未完成的工具执行已经安全结束；"
    "紧随其后的用户消息是本次引导，请立即按该引导继续。"
)
INTERRUPTED_TOOL_MESSAGE_CONTENT = "工具执行因用户引导或停止操作而中断，未产生可用结果。"


@dataclass(frozen=True, slots=True)
class StoppedTurn:
    state: RuntimeState
    messages: list[Any]


def close_stopped_turn_checkpoint(
    *,
    compiled_app: Any,
    thread_id: str,
    base_state: RuntimeState,
    visible_output: VisibleAssistantMessage,
    fallback_user_input: str,
    stop_reason: str = "user_cancelled",
) -> StoppedTurn:
    values = _checkpoint_values(compiled_app, thread_id=thread_id)
    checkpoint_state = _checkpoint_runtime_state(values) or base_state
    stopped_state = _stopped_runtime_state(
        checkpoint_state,
        visible_output=visible_output,
        fallback_user_input=fallback_user_input,
    )
    messages = _stopped_messages(
        values.get("messages"),
        visible_output=visible_output,
        stop_reason=stop_reason,
    )
    compiled_app.graph_app.update_state(
        {"configurable": {"thread_id": thread_id}},
        {
            "runtime": stopped_state.model_dump(mode="python"),
            "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *messages],
        },
        as_node=LANGGRAPH_INPUT_NODE,
    )
    return StoppedTurn(state=stopped_state, messages=messages)


def _checkpoint_values(compiled_app: Any, *, thread_id: str) -> dict[str, Any]:
    try:
        snapshot = compiled_app.graph_app.get_state({"configurable": {"thread_id": thread_id}})
    except Exception:
        return {}
    values = getattr(snapshot, "values", {}) or {}
    return dict(values) if isinstance(values, dict) else {}


def _checkpoint_runtime_state(values: dict[str, Any]) -> RuntimeState | None:
    runtime = values.get("runtime")
    if runtime is None:
        return None
    try:
        return RuntimeState.model_validate(runtime)
    except Exception:
        return None


def _stopped_runtime_state(
    state: RuntimeState,
    *,
    visible_output: VisibleAssistantMessage,
    fallback_user_input: str,
) -> RuntimeState:
    stopped = state.model_copy(deep=True)
    content = str(visible_output.content or stopped.conversation.assistant_draft or "").strip()
    reasoning_content = str(visible_output.reasoning_content or stopped.conversation.reasoning_content or "").strip()
    if fallback_user_input and not stopped.conversation.current_user_input:
        stopped.conversation.current_user_input = fallback_user_input
    stopped.conversation.assistant_draft = content or None
    stopped.conversation.final_answer = content or None
    stopped.conversation.reasoning_content = reasoning_content or None
    stopped.policy.interrupted = False
    stopped.policy.interrupt_required = False
    stopped.policy.approval_required = False
    stopped.execution.finished = True
    stopped.execution.finish_status = "stopped"
    stopped.execution.interrupted = False
    stopped.execution.last_error = None
    stopped.execution.last_error_location = None
    return stopped


def _stopped_messages(
    raw_messages: Any,
    *,
    visible_output: VisibleAssistantMessage,
    stop_reason: str,
) -> list[Any]:
    messages = close_incomplete_tool_call_history(
        list(raw_messages or []),
        content=INTERRUPTED_TOOL_MESSAGE_CONTENT,
    )
    assistant_message = _assistant_message(visible_output)
    if assistant_message is not None:
        messages.append(assistant_message)
    messages.append(
        HumanMessage(
            content=USER_STEER_MARKER_CONTENT if stop_reason == "user_steered" else USER_STOP_MARKER_CONTENT,
            additional_kwargs={
                "factory_control": {
                    "type": "user_steered_generation" if stop_reason == "user_steered" else "user_stopped_generation"
                }
            },
        )
    )
    return messages


def _assistant_message(visible_output: VisibleAssistantMessage) -> AIMessage | None:
    content = str(visible_output.content or "").strip()
    reasoning_content = str(visible_output.reasoning_content or "").strip()
    if not content and not reasoning_content:
        return None
    return AIMessage(
        content=content,
        additional_kwargs={"reasoning_content": reasoning_content} if reasoning_content else {},
    )
