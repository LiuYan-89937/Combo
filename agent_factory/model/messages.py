from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal, TypeAlias

from agent_factory.model.types import (
    AIMessage,
    AssistantMessage,
    HumanMessage,
    LLMMessage,
    LLMRequest,
    SystemMessage,
    ToolMessage,
    UserMessage,
)

MessageRole: TypeAlias = Literal["system", "user", "assistant", "tool"]
MessageLike: TypeAlias = LLMMessage | str | tuple[str, str] | Mapping[str, Any]


def message_from_role(
    role: MessageRole,
    content: str,
    *,
    name: str | None = None,
    tool_call_id: str | None = None,
) -> LLMMessage:
    if role == "system":
        return SystemMessage(content=content, name=name)
    if role == "user":
        return UserMessage(content=content, name=name)
    if role == "assistant":
        return AssistantMessage(content=content, name=name)
    if role == "tool":
        if tool_call_id is None:
            raise ValueError("ToolMessage requires tool_call_id")
        return ToolMessage(content=content, tool_call_id=tool_call_id, name=name)
    raise ValueError(f"Unsupported message role: {role}")


def normalize_message(message: MessageLike, *, default_role: MessageRole = "user") -> LLMMessage:
    if isinstance(message, LLMMessage):
        return message
    if isinstance(message, str):
        return message_from_role(default_role, message)
    if isinstance(message, tuple):
        role, content = message
        return message_from_role(role, content)  # type: ignore[arg-type]
    if isinstance(message, Mapping):
        data = dict(message)
        role = data.pop("role", default_role)
        content = data.pop("content")
        return message_from_role(role, content, **data)  # type: ignore[arg-type]
    raise TypeError(f"Unsupported message type: {type(message).__name__}")


def normalize_messages(
    messages: Iterable[MessageLike],
    *,
    default_role: MessageRole = "user",
) -> list[LLMMessage]:
    return [normalize_message(message, default_role=default_role) for message in messages]


class MessageFactory:
    """Fast constructors for role-specific messages."""

    @staticmethod
    def system(content: str, *, name: str | None = None) -> SystemMessage:
        return SystemMessage(content=content, name=name)

    @staticmethod
    def user(content: str, *, name: str | None = None) -> UserMessage:
        return UserMessage(content=content, name=name)

    @staticmethod
    def human(content: str, *, name: str | None = None) -> HumanMessage:
        return HumanMessage(content=content, name=name)

    @staticmethod
    def assistant(content: str, *, name: str | None = None) -> AssistantMessage:
        return AssistantMessage(content=content, name=name)

    @staticmethod
    def ai(content: str, *, name: str | None = None) -> AIMessage:
        return AIMessage(content=content, name=name)

    @staticmethod
    def tool(
        content: str,
        *,
        tool_call_id: str,
        name: str | None = None,
    ) -> ToolMessage:
        return ToolMessage(content=content, tool_call_id=tool_call_id, name=name)

    @staticmethod
    def from_any(message: MessageLike, *, default_role: MessageRole = "user") -> LLMMessage:
        return normalize_message(message, default_role=default_role)


class MessageBuilder:
    """Mutable builder for chat messages and requests."""

    def __init__(self, messages: Iterable[MessageLike] | None = None):
        self._messages = normalize_messages(messages or [])

    @classmethod
    def start(cls) -> "MessageBuilder":
        return cls()

    def add(self, message: MessageLike, *, default_role: MessageRole = "user") -> "MessageBuilder":
        self._messages.append(normalize_message(message, default_role=default_role))
        return self

    def extend(
        self,
        messages: Iterable[MessageLike],
        *,
        default_role: MessageRole = "user",
    ) -> "MessageBuilder":
        self._messages.extend(normalize_messages(messages, default_role=default_role))
        return self

    def system(self, content: str, *, name: str | None = None) -> "MessageBuilder":
        return self.add(MessageFactory.system(content, name=name))

    def user(self, content: str, *, name: str | None = None) -> "MessageBuilder":
        return self.add(MessageFactory.user(content, name=name))

    def assistant(self, content: str, *, name: str | None = None) -> "MessageBuilder":
        return self.add(MessageFactory.assistant(content, name=name))

    def tool(
        self,
        content: str,
        *,
        tool_call_id: str,
        name: str | None = None,
    ) -> "MessageBuilder":
        return self.add(MessageFactory.tool(content, tool_call_id=tool_call_id, name=name))

    def history(self, messages: Iterable[MessageLike]) -> "MessageBuilder":
        return self.extend(messages)

    def build(self) -> list[LLMMessage]:
        return list(self._messages)

    def request(
        self,
        *,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        response_format: Literal["text", "json_object", "json_schema"] = "text",
        json_schema: dict[str, Any] | None = None,
        json_schema_name: str | None = None,
        json_schema_strict: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> LLMRequest:
        return LLMRequest(
            messages=self.build(),
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            response_format=response_format,
            json_schema=json_schema,
            json_schema_name=json_schema_name,
            json_schema_strict=json_schema_strict,
            metadata=metadata or {},
        )

    def __len__(self) -> int:
        return len(self._messages)

    def __iter__(self):
        return iter(self.build())


def messages_to_request(
    messages: Sequence[MessageLike],
    *,
    temperature: float | None = None,
    max_output_tokens: int | None = None,
    response_format: Literal["text", "json_object", "json_schema"] = "text",
    json_schema: dict[str, Any] | None = None,
    json_schema_name: str | None = None,
    json_schema_strict: bool = True,
    metadata: dict[str, Any] | None = None,
) -> LLMRequest:
    return MessageBuilder(messages).request(
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        response_format=response_format,
        json_schema=json_schema,
        json_schema_name=json_schema_name,
        json_schema_strict=json_schema_strict,
        metadata=metadata,
    )
