from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from agent_factory.factory_graph.frontend_bridge.event_normalizer import VisibleAssistantMessage
from agent_factory.runtime_kernel.state import RuntimeState
from agent_factory.runtime_protocol.messages import incomplete_tool_call_ids


LANGGRAPH_INPUT_NODE = "__input__"
USER_STOP_MARKER_CONTENT = (
    "用户已停止上一条助手回复。请将上一条助手回复视为已被用户中断，等待并遵循下一条用户消息继续。"
)


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
) -> list[Any]:
    messages = _complete_message_prefix(list(raw_messages or []))
    assistant_message = _assistant_message(visible_output)
    if assistant_message is not None:
        messages.append(assistant_message)
    messages.append(
        HumanMessage(
            content=USER_STOP_MARKER_CONTENT,
            additional_kwargs={"factory_control": {"type": "user_stopped_generation"}},
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


def _complete_message_prefix(messages: list[Any]) -> list[Any]:
    for index in range(len(messages), -1, -1):
        prefix = messages[:index]
        if not incomplete_tool_call_ids(prefix):
            return prefix
    return []
