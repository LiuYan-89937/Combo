from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from combo.runtime_kernel.model_message_content import message_text


EXECUTOR_NODE_ID = "executor"
RECENT_EXECUTOR_TOOL_EXCHANGES = 1


def project_model_history(
    *, state: Any, messages: list[BaseMessage], node_id: str | None,
) -> list[BaseMessage]:
    if getattr(getattr(state, "run", None), "strategy", None) != "plan_and_execute":
        return messages
    if node_id != EXECUTOR_NODE_ID:
        return messages

    projected: list[BaseMessage] = []
    current_user = _current_user_message(state=state, messages=messages)
    if current_user is not None:
        projected.append(current_user)
    projected.extend(_recent_tool_exchanges(messages))
    return projected or messages[-1:]


def _current_user_message(*, state: Any, messages: list[BaseMessage]) -> HumanMessage | None:
    current_id = getattr(getattr(state, "conversation", None), "current_user_input_id", None)
    if current_id:
        for message in reversed(messages):
            if isinstance(message, HumanMessage) and message.id == current_id:
                return message
    current_input = str(getattr(getattr(state, "conversation", None), "current_user_input", "") or "").strip()
    for message in reversed(messages):
        if not isinstance(message, HumanMessage):
            continue
        if not current_input or message_text(message).strip() == current_input:
            return message
    if current_input:
        return HumanMessage(content=current_input, id=current_id)
    return next((message for message in reversed(messages) if isinstance(message, HumanMessage)), None)


def _recent_tool_exchanges(messages: list[BaseMessage]) -> list[BaseMessage]:
    exchanges: list[list[BaseMessage]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if not _is_executor_tool_call(message):
            index += 1
            continue
        tool_call_ids = _tool_call_ids(message)
        exchange: list[BaseMessage] = [message]
        cursor = index + 1
        pending = set(tool_call_ids)
        while cursor < len(messages):
            candidate = messages[cursor]
            if not isinstance(candidate, ToolMessage):
                break
            candidate_id = str(getattr(candidate, "tool_call_id", "") or "")
            if not pending or candidate_id in pending:
                exchange.append(candidate)
                pending.discard(candidate_id)
            cursor += 1
        if tool_call_ids and not pending:
            exchanges.append(exchange)
        index = max(cursor, index + 1)
    selected = exchanges[-RECENT_EXECUTOR_TOOL_EXCHANGES:]
    return [message for exchange in selected for message in exchange]


def _is_executor_tool_call(message: BaseMessage) -> bool:
    if not isinstance(message, AIMessage) or not _tool_call_ids(message):
        return False
    metadata = dict(message.additional_kwargs or {})
    return str(metadata.get("combo_origin_node_id") or "") == EXECUTOR_NODE_ID


def _tool_call_ids(message: BaseMessage) -> list[str]:
    if not isinstance(message, AIMessage):
        return []
    ids: list[str] = []
    for call in [*(message.tool_calls or []), *(message.invalid_tool_calls or [])]:
        if not isinstance(call, dict):
            continue
        call_id = str(call.get("id") or call.get("tool_call_id") or "").strip()
        if call_id:
            ids.append(call_id)
    return ids
