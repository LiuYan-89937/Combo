from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool

from agent_factory.models import get_main_model, get_main_model_settings
from agent_factory.runtime_kernel.types import ModelInvocationResult


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
    """RuntimeKernel model adapter backed by the configured Factory main model.

    This adapter deliberately performs only model invocation. It does not plan
    tools, choose routes, approve actions, or synthesize graph control.
    """

    def generate(
        self,
        *,
        state: Any,
        prompt_binding: dict[str, Any] | None = None,
        messages: list[Any] | None = None,
        tools: list[BaseTool] | None = None,
    ) -> ModelInvocationResult:
        model = get_main_model()
        settings = get_main_model_settings()
        if model is None:
            raise RuntimeError("main model is not configured for AgentPackage runtime")
        bound_model = model.bind_tools(tools) if tools else model
        response = bound_model.invoke(
            _messages_for_state(
                state=state,
                prompt_binding=prompt_binding or {},
                messages=messages or [],
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


def _messages_for_state(*, state: Any, prompt_binding: dict[str, Any], messages: list[Any]) -> list[Any]:
    system_parts = []
    template = str(prompt_binding.get("template") or "").strip()
    if template:
        system_parts.append(template)
    else:
        system_parts.append("You are the generated Agent runtime model. Answer the user directly and concisely.")
    memory_text = _cross_session_memory_text(state)
    if memory_text:
        system_parts.append(memory_text)
    normalized_messages = [message for message in messages if isinstance(message, BaseMessage)]
    if not normalized_messages:
        user_input = str(getattr(getattr(state, "conversation", None), "current_user_input", "") or "")
        if user_input:
            normalized_messages = [HumanMessage(content=user_input)]
    return [SystemMessage(content="\n\n".join(system_parts)), *normalized_messages]


def _tool_calls_from_response(response: Any) -> list[dict[str, Any]]:
    calls = getattr(response, "tool_calls", None) or []
    normalized: list[dict[str, Any]] = []
    for index, call in enumerate(calls):
        if not isinstance(call, dict):
            continue
        name = str(call.get("name") or "")
        if not name:
            continue
        args = call.get("args")
        normalized.append(
            {
                "name": name,
                "args": dict(args) if isinstance(args, dict) else {},
                "id": str(call.get("id") or f"call_{index}_{name}"),
                "type": "tool_call",
            }
        )
    return normalized


def _cross_session_memory_text(state: Any) -> str:
    context = getattr(getattr(state, "context", None), "model_context", {}) or {}
    pack = context.get("cross_session_memory") if isinstance(context, dict) else None
    if not isinstance(pack, dict):
        return ""
    items = pack.get("items")
    if not isinstance(items, list) or not items:
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
    return "Relevant persistent context:\n" + "\n".join(lines)


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
