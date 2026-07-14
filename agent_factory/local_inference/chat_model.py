from __future__ import annotations

import json
import re
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


class LocalLlamaCppChatModel(BaseChatModel):
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
        return "local_llama_cpp_rocm"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model_name": self.model_name, "transport": "local_llama_cpp"}

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
            _raise_for_local_inference_error(response)
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

    def get_token_ids(self, text: str) -> list[int]:
        with httpx.Client(timeout=self.endpoint.timeout_seconds) as client:
            response = client.post(
                self.endpoint.server_endpoint("/tokenize"),
                json={"content": text, "add_special": False},
            )
            _raise_for_local_inference_error(response)
            payload = response.json()
        tokens = payload.get("tokens") if isinstance(payload, dict) else None
        if not isinstance(tokens, list) or not all(isinstance(token, int) for token in tokens):
            raise ValueError("llama-server tokenize response does not contain integer tokens")
        return tokens


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
    content = raw_message.get("content") or ""
    if not tool_calls:
        tool_calls = _xml_tool_calls(content)
        if tool_calls:
            content = _without_xml_tool_calls(content)
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
        content=content,
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
        raise ValueError("local llama.cpp response does not contain a valid choice")
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


def _raise_for_local_inference_error(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = _local_inference_error_detail(response)
        if detail:
            raise RuntimeError(
                f"local llama.cpp request failed with HTTP {response.status_code}: {detail}"
            ) from exc
        raise


def _local_inference_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return response.text.strip()
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("detail") or "").strip()
    return str(payload.get("detail") or payload.get("message") or "").strip()


_XML_TOOL_CALL_PATTERN = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
_XML_FUNCTION_PATTERN = re.compile(r"<function=([^>]+)>(.*?)</function>", re.DOTALL)
_XML_PARAMETER_PATTERN = re.compile(r"<parameter=([^>]+)>\s*(.*?)\s*</parameter>", re.DOTALL)


def _xml_tool_calls(content: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for index, match in enumerate(_XML_TOOL_CALL_PATTERN.finditer(content)):
        body = match.group(1).strip()
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = _function_xml_payload(body)
        if not isinstance(payload, dict):
            continue
        name = str(payload.get("name") or "").strip()
        arguments = payload.get("arguments")
        if not name or not isinstance(arguments, dict):
            continue
        calls.append({"id": f"call_xml_{index}_{uuid4().hex}", "name": name, "args": arguments, "type": "tool_call"})
    return calls


def _function_xml_payload(body: str) -> dict[str, Any] | None:
    match = _XML_FUNCTION_PATTERN.search(body)
    if match is None:
        return None
    arguments: dict[str, Any] = {}
    for parameter in _XML_PARAMETER_PATTERN.finditer(match.group(2)):
        key = parameter.group(1).strip()
        raw_value = parameter.group(2).strip()
        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError:
            value = raw_value
        if key:
            arguments[key] = value
    return {"name": match.group(1).strip(), "arguments": arguments}


def _without_xml_tool_calls(content: str) -> str:
    return _XML_TOOL_CALL_PATTERN.sub("", content).strip()
