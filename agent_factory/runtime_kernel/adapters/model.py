from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any, Literal, Protocol

from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool

from agent_factory.models import (
    ChatModelSettings,
    get_compression_model,
    get_compression_model_settings,
    get_main_model,
    get_main_model_settings,
    get_task_model,
    get_task_model_settings,
)
from agent_factory.runtime_kernel.model_inputs import build_runtime_model_input
from agent_factory.runtime_kernel.types import ModelInvocationResult


ModelRole = Literal["main", "task", "compression"]
_INTERNAL_SESSION_SNAPSHOT_BLOCK_RE = re.compile(
    r"<session_snapshot\b[^>]*>.*?</session_snapshot>",
    re.IGNORECASE | re.DOTALL,
)
_INTERNAL_SESSION_SNAPSHOT_OPEN_RE = re.compile(
    r"<session_snapshot\b[^>]*>.*$",
    re.IGNORECASE,
)


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

    def __init__(
        self,
        *,
        role: ModelRole = "main",
        model: Any | None = None,
        settings: ChatModelSettings | None = None,
    ) -> None:
        self.model_role = role
        self._model = model
        self._settings = settings

    def generate(
        self,
        *,
        state: Any,
        prompt_binding: dict[str, Any] | None = None,
        messages: list[Any] | None = None,
        tools: list[BaseTool] | None = None,
    ) -> ModelInvocationResult:
        model, settings = self._resolve_model()
        if model is None:
            raise RuntimeError(f"{self.model_role} model is not configured for AgentPackage runtime")
        bound_model = _bind_tools(model, tools or [])
        envelope = build_runtime_model_input(
            state=state,
            prompt_binding=prompt_binding or {},
            messages=messages or [],
            tools=tools or [],
        )
        response = bound_model.invoke(
            envelope.messages
        )
        text = strip_internal_snapshot_blocks(_content_to_text(getattr(response, "content", response))).strip()
        tool_calls = _tool_calls_from_response(response)
        return ModelInvocationResult(
            ai_message=response if isinstance(response, BaseMessage) else None,
            assistant_draft=text,
            final_answer=None if tool_calls else text,
            tool_calls=tool_calls,
            metadata={
                **settings.metadata(),
                "tool_count": len(tools or []),
                **envelope.diagnostics(),
            },
        )

    def _resolve_model(self) -> tuple[Any, ChatModelSettings]:
        if self._model is not None and self._settings is not None:
            return self._model, self._settings
        return _configured_model_for_role(self.model_role)


def _configured_model_for_role(role: ModelRole) -> tuple[Any, ChatModelSettings]:
    if role == "main":
        return get_main_model(), get_main_model_settings()
    if role == "task":
        return get_task_model(), get_task_model_settings()
    if role == "compression":
        return get_compression_model(), get_compression_model_settings()
    raise ValueError(f"unsupported model role: {role}")


def _bind_tools(model: Any, tools: list[BaseTool]) -> Any:
    if not tools:
        return model
    return model.bind_tools(tools, tool_choice="auto")


def strip_internal_snapshot_blocks(value: str) -> str:
    """Remove private context snapshots only when text is leaving the model as user-visible output."""
    if not value:
        return ""
    text = _INTERNAL_SESSION_SNAPSHOT_BLOCK_RE.sub("", value)
    text = _INTERNAL_SESSION_SNAPSHOT_OPEN_RE.sub("", text)
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line.strip()).strip()


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
