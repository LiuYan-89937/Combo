from __future__ import annotations

import json
from typing import Any, Sequence
from uuid import uuid4

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ConfigDict, Field

from agent_factory.local_inference.config import LocalInferenceEndpoint


class LocalVllmChatModel(BaseChatModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    model_name: str
    endpoint: LocalInferenceEndpoint
    temperature: float | None = None
    max_output_tokens: int | None = None
    reasoning_enabled: bool | None = None
    bound_tools: list[dict[str, Any]] = Field(default_factory=list)
    bound_tool_choice: str | dict[str, Any] | None = None

    @property
    def _llm_type(self) -> str:
        return "local_vllm_rocm"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model_name": self.model_name, "transport": "local_vllm"}

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ):
        converted = [convert_to_openai_tool(tool) for tool in tools]
        return self.model_copy(
            update={
                "bound_tools": converted,
                "bound_tool_choice": tool_choice,
            },
            deep=True,
        )

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,
        **kwargs: Any,
    ) -> ChatResult:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [_message_payload(message) for message in messages],
            "stream": False,
        }
        tools = kwargs.get("tools") or self.bound_tools
        tool_choice = kwargs.get("tool_choice") or self.bound_tool_choice
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.max_output_tokens is not None:
            payload["max_tokens"] = self.max_output_tokens
        if stop:
            payload["stop"] = stop
        if self.reasoning_enabled is not None:
            payload["chat_template_kwargs"] = {"enable_thinking": self.reasoning_enabled}

        with httpx.Client(timeout=self.endpoint.timeout_seconds) as client:
            response = client.post(self.endpoint.endpoint("/chat/completions"), json=payload)
            response.raise_for_status()
            body = response.json()
        message = _response_message(body)
        generation_info = {
            "finish_reason": _choice(body).get("finish_reason"),
            "model": str(body.get("model") or self.model_name),
        }
        return ChatResult(
            generations=[ChatGeneration(message=message, generation_info=generation_info)],
            llm_output={"usage": dict(body.get("usage") or {}), "model": generation_info["model"]},
        )


def _message_payload(message: BaseMessage) -> dict[str, Any]:
    if isinstance(message, SystemMessage):
        role = "system"
    elif isinstance(message, HumanMessage):
        role = "user"
    elif isinstance(message, ToolMessage):
        return {
            "role": "tool",
            "content": message.content,
            "tool_call_id": message.tool_call_id,
        }
    elif isinstance(message, AIMessage):
        payload: dict[str, Any] = {"role": "assistant", "content": message.content}
        if message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": str(call.get("id") or uuid4().hex),
                    "type": "function",
                    "function": {
                        "name": str(call.get("name") or ""),
                        "arguments": json.dumps(call.get("args") or {}, ensure_ascii=False),
                    },
                }
                for call in message.tool_calls
            ]
        reasoning = message.additional_kwargs.get("reasoning_content")
        if reasoning is not None:
            payload["reasoning_content"] = reasoning
        return payload
    else:
        role = str(getattr(message, "type", "user") or "user")
    return {"role": role, "content": message.content}


def _response_message(body: dict[str, Any]) -> AIMessage:
    choice = _choice(body)
    raw_message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    tool_calls = []
    for item in raw_message.get("tool_calls") or []:
        if not isinstance(item, dict):
            continue
        function = item.get("function") if isinstance(item.get("function"), dict) else {}
        name = str(function.get("name") or "")
        if not name:
            continue
        tool_calls.append(
            {
                "id": str(item.get("id") or uuid4().hex),
                "name": name,
                "args": _tool_arguments(function.get("arguments")),
                "type": "tool_call",
            }
        )
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    usage_metadata = {
        "input_tokens": int(usage.get("prompt_tokens") or 0),
        "output_tokens": int(usage.get("completion_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
    }
    additional_kwargs: dict[str, Any] = {}
    if raw_message.get("reasoning_content") is not None:
        additional_kwargs["reasoning_content"] = raw_message.get("reasoning_content")
    return AIMessage(
        content=raw_message.get("content") or "",
        tool_calls=tool_calls,
        additional_kwargs=additional_kwargs,
        usage_metadata=usage_metadata,
        response_metadata={
            "finish_reason": choice.get("finish_reason"),
            "model": body.get("model"),
        },
    )


def _choice(body: dict[str, Any]) -> dict[str, Any]:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("local vLLM response does not contain a valid choice")
    return choices[0]


def _tool_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {"value": value}
    return parsed if isinstance(parsed, dict) else {"value": parsed}
