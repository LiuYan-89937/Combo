from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from agent_factory.runtime_protocol import (
    ArtifactPart,
    CapabilitySnapshot,
    ConversationMessage,
    DiagnosticPart,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)
from agent_factory.runtime_kernel.planning import RUNTIME_PLAN_TOOL_ID


def conversation_to_graph_messages(messages: list[ConversationMessage]) -> list[BaseMessage]:
    projected: list[BaseMessage] = []
    for message in messages:
        if message.status == "cancelled":
            continue
        text = _text_content(message)
        if message.role == "user":
            projected.append(HumanMessage(content=text, id=message.message_id))
            continue
        if message.role == "assistant":
            tool_calls = [
                {
                    "name": part.model_alias,
                    "args": dict(part.arguments),
                    "id": part.tool_call_id,
                    "type": "tool_call",
                }
                for part in message.parts
                if isinstance(part, ToolCallPart)
            ]
            if text or tool_calls:
                projected.append(
                    AIMessage(
                        content=text,
                        id=message.message_id,
                        tool_calls=tool_calls,
                        additional_kwargs=(
                            {"completion_reason": message.completion_reason}
                            if message.completion_reason
                            else {}
                        ),
                    )
                )
            continue
        for part in message.parts:
            if not isinstance(part, ToolResultPart):
                continue
            projected.append(
                ToolMessage(
                    content=json.dumps(
                        {
                            "status": part.status,
                            "output": part.output,
                            "error_code": part.error_code,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    tool_call_id=part.tool_call_id,
                    id=f"{message.message_id}:{part.tool_call_id}",
                )
            )
    return projected


def graph_messages_to_conversation(
    *,
    graph_messages: list[BaseMessage],
    current_user_message_id: str,
    session_id: str,
    turn_id: str,
    runtime_instance_id: str,
    request_id: str,
    task_revision: int,
    capability_snapshot: CapabilitySnapshot,
) -> list[ConversationMessage]:
    boundary = _current_turn_boundary(graph_messages, current_user_message_id)
    aliases = {
        item.model_alias: item
        for item in capability_snapshot.tool_aliases
    }
    projected: list[ConversationMessage] = []
    internal_tool_call_ids: set[str] = set()
    for message in graph_messages[boundary + 1 :]:
        if isinstance(message, AIMessage):
            parts: list[Any] = []
            content = _message_text(message)
            if content:
                parts.append(TextPart(text=content))
            for call in list(message.tool_calls or []):
                alias = str(call.get("name") or "").strip()
                tool_call_id = str(call.get("id") or "").strip()
                if alias == RUNTIME_PLAN_TOOL_ID:
                    if tool_call_id:
                        internal_tool_call_ids.add(tool_call_id)
                    continue
                binding = aliases.get(alias)
                if not alias or binding is None:
                    raise ValueError(f"graph tool call is not present in capability snapshot: {alias or '<empty>'}")
                parts.append(
                    ToolCallPart(
                        tool_call_id=tool_call_id,
                        capability_id=binding.capability_id,
                        capability_revision=binding.revision,
                        model_alias=alias,
                        arguments=_json_object(call.get("args")),
                    )
                )
            if parts:
                projected.append(
                    _runtime_message(
                        message_id=getattr(message, "id", None),
                        session_id=session_id,
                        turn_id=turn_id,
                        role="assistant",
                        parts=parts,
                        runtime_instance_id=runtime_instance_id,
                        request_id=request_id,
                        task_revision=task_revision,
                        completion_reason=_completion_reason(message),
                    )
                )
            continue
        if isinstance(message, ToolMessage):
            if message.tool_call_id in internal_tool_call_ids:
                continue
            result = _tool_result_part(message)
            projected.append(
                _runtime_message(
                    message_id=getattr(message, "id", None),
                    session_id=session_id,
                    turn_id=turn_id,
                    role="tool",
                    parts=[result],
                    runtime_instance_id=runtime_instance_id,
                    request_id=request_id,
                    task_revision=task_revision,
                )
            )
    return projected


def _runtime_message(
    *,
    message_id: Any,
    session_id: str,
    turn_id: str,
    role: str,
    parts: list[Any],
    runtime_instance_id: str,
    request_id: str,
    task_revision: int,
    completion_reason: str | None = None,
) -> ConversationMessage:
    payload: dict[str, Any] = {
        "session_id": session_id,
        "turn_id": turn_id,
        "role": role,
        "parts": tuple(parts),
        "source_runtime_instance_id": runtime_instance_id,
        "source_request_id": request_id,
        "source_task_revision": task_revision,
        "completion_reason": completion_reason,
    }
    value = str(message_id or "").strip()
    if value:
        payload["message_id"] = value
    return ConversationMessage.model_validate(payload)


def _completion_reason(message: BaseMessage) -> str | None:
    value = str(getattr(message, "additional_kwargs", {}).get("completion_reason") or "").strip()
    return value or None


def _current_turn_boundary(messages: list[BaseMessage], message_id: str) -> int:
    for index in range(len(messages) - 1, -1, -1):
        if str(getattr(messages[index], "id", "") or "") == message_id:
            return index
    raise ValueError("current user message is missing from graph conversation projection")


def _text_content(message: ConversationMessage) -> str:
    chunks: list[str] = []
    for part in message.parts:
        if isinstance(part, TextPart):
            chunks.append(part.text)
        elif isinstance(part, ArtifactPart):
            chunks.append(f"[artifact:{part.artifact_id}@{part.revision}]")
        elif isinstance(part, DiagnosticPart):
            chunks.append(f"[diagnostic:{part.user_message_key}]")
    return "\n".join(chunks)


def _message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if isinstance(part, str):
                chunks.append(part)
            elif isinstance(part, dict) and part.get("type") in {"text", "output_text"}:
                chunks.append(str(part.get("text") or ""))
        return "\n".join(item.strip() for item in chunks if item.strip())
    return str(content or "").strip()


def _tool_result_part(message: ToolMessage) -> ToolResultPart:
    payload = _json_object_or_text(message.content)
    raw_status = str(payload.get("status") or payload.get("execution_status") or "completed").strip()
    status = {
        "completed": "completed",
        "success": "completed",
        "failed": "failed",
        "execution_failed": "failed",
        "cancelled": "cancelled",
        "rejected": "rejected",
        "tool_not_allowed": "rejected",
        "timed_out": "timed_out",
        "timeout": "timed_out",
    }.get(raw_status, "failed")
    if status == "completed":
        output = payload.get("output")
        return ToolResultPart(
            tool_call_id=message.tool_call_id,
            status="completed",
            output=_json_object(output if output is not None else payload),
        )
    return ToolResultPart(
        tool_call_id=message.tool_call_id,
        status=status,
        error_code=str(payload.get("error_code") or raw_status or "tool_failed"),
    )


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    if value is None:
        return {}
    return {"value": json.loads(json.dumps(value, ensure_ascii=False, default=str))}


def _json_object_or_text(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return _json_object(value)
    text = str(value or "")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"status": "completed", "output": {"text": text}}
    return _json_object(parsed)
