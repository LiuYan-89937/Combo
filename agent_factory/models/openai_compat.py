from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import ChatOpenAI


class ThinkingCompatibleChatOpenAI(ChatOpenAI):
    """ChatOpenAI adapter for OpenAI-compatible thinking-mode providers."""

    preserve_reasoning_content: bool = False

    def _get_request_payload(self, input_: Any, *, stop: list[str] | None = None, **kwargs: Any) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        if not self.preserve_reasoning_content:
            return payload
        source_messages = self._convert_input(input_).to_messages()
        payload_messages = payload.get("messages")
        if isinstance(payload_messages, list):
            _patch_reasoning_content_payload(payload_messages, source_messages)
        return payload

    def _create_chat_result(self, response: Any, generation_info: dict | None = None):
        result = super()._create_chat_result(response, generation_info)
        response_dict = response if isinstance(response, dict) else response.model_dump()
        choices = response_dict.get("choices") or []
        for generation, choice in zip(result.generations, choices, strict=False):
            message = generation.message
            if not isinstance(message, AIMessage):
                continue
            reasoning_content = _reasoning_content_from_raw_message(choice.get("message") or {})
            if reasoning_content is not None:
                message.additional_kwargs["reasoning_content"] = reasoning_content
        return result


def _patch_reasoning_content_payload(
    payload_messages: list[dict[str, Any]],
    source_messages: list[BaseMessage],
) -> None:
    source_index = 0
    for payload_message in payload_messages:
        if payload_message.get("role") != "assistant":
            continue
        source_entry = _next_ai_message(source_messages, source_index)
        if source_entry is None:
            continue
        source_index, source_message = source_entry
        source_index += 1
        reasoning_content = _reasoning_content_from_ai_message(source_message)
        if reasoning_content is not None:
            payload_message["reasoning_content"] = reasoning_content
        elif payload_message.get("tool_calls"):
            payload_message["reasoning_content"] = ""


def _next_ai_message(messages: list[BaseMessage], start: int) -> tuple[int, AIMessage] | None:
    for index, message in enumerate(messages[start:], start=start):
        if isinstance(message, AIMessage):
            return index, message
    return None


def _reasoning_content_from_raw_message(message: dict[str, Any]) -> str | None:
    return _coerce_reasoning_content(message.get("reasoning_content") or message.get("reasoning"))


def _reasoning_content_from_ai_message(message: AIMessage) -> str | None:
    candidates = [
        message.additional_kwargs.get("reasoning_content"),
        message.response_metadata.get("reasoning_content"),
        message.additional_kwargs.get("reasoning"),
        message.response_metadata.get("reasoning"),
        _reasoning_content_from_blocks(message.content),
    ]
    for candidate in candidates:
        reasoning_content = _coerce_reasoning_content(candidate)
        if reasoning_content is not None:
            return reasoning_content
    return None


def _reasoning_content_from_blocks(content: Any) -> str | None:
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") not in {"reasoning_content", "thinking", "reasoning"}:
            continue
        text = block.get("reasoning_content") or block.get("thinking") or block.get("text") or block.get("content")
        if text:
            parts.append(str(text))
    if not parts:
        return None
    return "\n".join(parts)


def _coerce_reasoning_content(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("reasoning_content", "text", "content", "summary"):
            if key in value:
                return _coerce_reasoning_content(value[key])
        return str(value)
    if isinstance(value, list):
        parts = [_coerce_reasoning_content(item) for item in value]
        return "\n".join(part for part in parts if part)
    return str(value)
