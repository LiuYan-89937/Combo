from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Literal, Protocol

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool

from agent_factory.context_system.compression import is_context_summary_message
from agent_factory.models import (
    ChatModelSettings,
    get_main_model,
    get_main_model_settings,
    get_task_model,
    get_task_model_settings,
)
from agent_factory.runtime_kernel.types import ModelInvocationResult


ModelRole = Literal["main", "task"]


class ModelServiceAdapter(Protocol):
    def generate(
        self,
        *,
        state: Any,
        prompt_binding: dict[str, Any] | None = None,
        messages: list[Any] | None = None,
        tools: list[BaseTool] | None = None,
    ) -> ModelInvocationResult:
        ...


class ScriptedModelService:
    def __init__(self, responses: Sequence[ModelInvocationResult] | None = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    def generate(
        self,
        *,
        state: Any,
        prompt_binding: dict[str, Any] | None = None,
        messages: list[Any] | None = None,
        tools: list[BaseTool] | None = None,
    ) -> ModelInvocationResult:
        self.calls.append({"state": state, "prompt_binding": prompt_binding or {}})
        if self._responses:
            return self._responses.pop(0)
        current_input = getattr(getattr(state, "conversation", None), "current_user_input", None)
        text = str(current_input or "")
        prompt_id = str((prompt_binding or {}).get("prompt_id") or "")
        if "clarify" in prompt_id and len(text.strip()) < 12:
            return ModelInvocationResult(
                assistant_draft="我需要更多信息来继续。",
                clarification_question="请补充你的目标或使用场景。",
            )
        return ModelInvocationResult(
            assistant_draft=f"Echo: {text}",
            final_answer=f"Echo: {text}",
        )


class LangChainModelServiceAdapter:
    """RuntimeKernel model adapter backed by a configured Factory model role.

    This adapter deliberately performs only model invocation. It does not plan
    tools, choose routes, approve actions, or synthesize graph control.
    """

    def __init__(self, *, role: ModelRole = "main") -> None:
        self.model_role = role

    def generate(
        self,
        *,
        state: Any,
        prompt_binding: dict[str, Any] | None = None,
        messages: list[Any] | None = None,
        tools: list[BaseTool] | None = None,
    ) -> ModelInvocationResult:
        model, settings = _configured_model_for_role(self.model_role)
        if model is None:
            raise RuntimeError(f"{self.model_role} model is not configured for AgentPackage runtime")
        bound_model = _bind_tools(model, tools or [])
        response = bound_model.invoke(
            _messages_for_state(
                state=state,
                prompt_binding=prompt_binding or {},
                messages=messages or [],
                tools=tools or [],
            )
        )
        text = _content_to_text(getattr(response, "content", response)).strip()
        tool_calls = _tool_calls_from_response(response)
        return ModelInvocationResult(
            ai_message=response if isinstance(response, BaseMessage) else None,
            assistant_draft=text,
            final_answer=None if tool_calls else text,
            tool_calls=tool_calls,
            metadata={
                "model_role": settings.role,
                "model": settings.model or "",
                "tool_count": len(tools or []),
            },
        )


def _configured_model_for_role(role: ModelRole) -> tuple[Any, ChatModelSettings]:
    if role == "main":
        return get_main_model(), get_main_model_settings()
    if role == "task":
        return get_task_model(), get_task_model_settings()
    raise ValueError(f"unsupported model role: {role}")


def _bind_tools(model: Any, tools: list[BaseTool]) -> Any:
    if not tools:
        return model
    return model.bind_tools(tools, tool_choice="auto")


def _messages_for_state(
    *,
    state: Any,
    prompt_binding: dict[str, Any],
    messages: list[Any],
    tools: list[BaseTool],
) -> list[Any]:
    system_parts = []
    template = str(prompt_binding.get("template") or "").strip()
    if template:
        system_parts.append(template)
    else:
        system_parts.append("You are the generated Agent runtime model. Answer the user directly and concisely.")
    if tools:
        system_parts.append(_tool_protocol_instruction(tools))
    summary_text = _conversation_summary_text(messages)
    if summary_text:
        system_parts.append(summary_text)
    context_text = _llm_context_text(state)
    if context_text:
        system_parts.append(context_text)
    normalized_messages = [
        message
        for message in messages
        if isinstance(message, BaseMessage) and not is_context_summary_message(message)
    ]
    if not normalized_messages:
        user_input = str(getattr(getattr(state, "conversation", None), "current_user_input", "") or "")
        if user_input:
            normalized_messages = [HumanMessage(content=user_input)]
    return [SystemMessage(content="\n\n".join(system_parts)), *normalized_messages]


def _conversation_summary_text(messages: list[Any]) -> str:
    summaries = [
        str(getattr(message, "content", "") or "").strip()
        for message in messages
        if is_context_summary_message(message)
    ]
    summaries = [summary for summary in summaries if summary]
    if not summaries:
        return ""
    return (
        "Internal compressed conversation memory. Use it only to maintain continuity. "
        "Do not quote, restate, or expose this summary to the user unless they explicitly ask for the prior conversation:\n"
        + "\n\n".join(summaries[-3:])
    )


def _tool_protocol_instruction(tools: list[BaseTool]) -> str:
    tool_names = ", ".join(tool.name for tool in tools)
    return (
        "Tool protocol: when a tool is needed, use the chat model's native tool_call mechanism only. "
        "Do not write tool calls as plain text, XML, JSON, markdown, or pseudo syntax. "
        "Use exact argument names from the tool schema. After receiving a tool observation, continue from the observation. "
        f"Available tools: {tool_names}."
    )


def _tool_calls_from_response(response: Any) -> list[dict[str, Any]]:
    calls = getattr(response, "tool_calls", None) or []
    if not calls:
        additional_kwargs = getattr(response, "additional_kwargs", None) or {}
        if isinstance(additional_kwargs, dict):
            calls = additional_kwargs.get("tool_calls") or []
    normalized: list[dict[str, Any]] = []
    for index, call in enumerate(calls):
        if not isinstance(call, dict):
            continue
        function = call.get("function") if isinstance(call.get("function"), dict) else {}
        name = str(call.get("name") or function.get("name") or "")
        if not name:
            continue
        args = call.get("args")
        if args is None:
            args = function.get("arguments")
        normalized.append(
            {
                "name": name,
                "args": _tool_call_args(args),
                "id": str(call.get("id") or f"call_{index}_{name}"),
                "type": "tool_call",
            }
        )
    return normalized


def _tool_call_args(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _llm_context_text(state: Any) -> str:
    context = getattr(getattr(state, "context", None), "model_context", {}) or {}
    frame = context.get("llm_context_frame") if isinstance(context, dict) else None
    if not isinstance(frame, dict):
        return ""
    text = str(frame.get("text") or "").strip()
    if text:
        return text
    items = frame.get("items")
    if not isinstance(items, list):
        return ""
    lines = []
    for item in items[:8]:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if content:
            lines.append(f"- {content}")
    if not lines:
        return ""
    return "Context that may help this response. Use only what is relevant and do not mention where it came from:\n" + "\n".join(lines)


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                value = item.get("text") or item.get("content")
                if value:
                    parts.append(str(value))
        return "\n".join(parts)
    return str(content)
