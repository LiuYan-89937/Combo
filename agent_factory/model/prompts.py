from __future__ import annotations

import string
from collections.abc import Iterable, Mapping
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.model.messages import MessageLike, MessageRole, normalize_messages
from agent_factory.model.types import LLMMessage, LLMRequest


PromptPart: TypeAlias = "MessageTemplate | MessagesPlaceholder | LLMMessage | tuple[str, str] | str"


def _template_variables(template: str) -> set[str]:
    variables: set[str] = set()
    formatter = string.Formatter()
    for _, field_name, _, _ in formatter.parse(template):
        if field_name:
            variables.add(field_name.split(".", 1)[0].split("[", 1)[0])
    return variables


class PromptTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: str
    input_variables: set[str] = Field(default_factory=set)

    @classmethod
    def from_template(cls, template: str) -> "PromptTemplate":
        return cls(template=template, input_variables=_template_variables(template))

    def format(self, **values: Any) -> str:
        missing = self.input_variables.difference(values)
        if missing:
            joined = ", ".join(sorted(missing))
            raise ValueError(f"Missing prompt variables: {joined}")
        return self.template.format(**values)

    def message(self, role: MessageRole, **values: Any) -> LLMMessage:
        return LLMMessage(role=role, content=self.format(**values))


class MessageTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: MessageRole
    template: PromptTemplate
    name: str | None = None
    tool_call_id: str | None = None

    @classmethod
    def from_template(
        cls,
        role: MessageRole,
        template: str,
        *,
        name: str | None = None,
        tool_call_id: str | None = None,
    ) -> "MessageTemplate":
        return cls(
            role=role,
            template=PromptTemplate.from_template(template),
            name=name,
            tool_call_id=tool_call_id,
        )

    def render(self, values: Mapping[str, Any]) -> LLMMessage:
        return LLMMessage(
            role=self.role,
            content=self.template.format(**dict(values)),
            name=self.name,
            tool_call_id=self.tool_call_id,
        )


class MessagesPlaceholder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variable_name: str
    optional: bool = False

    def render(self, values: Mapping[str, Any]) -> list[LLMMessage]:
        if self.variable_name not in values:
            if self.optional:
                return []
            raise ValueError(f"Missing messages placeholder: {self.variable_name}")
        raw_messages = values[self.variable_name]
        if raw_messages is None and self.optional:
            return []
        if isinstance(raw_messages, (str, LLMMessage)) or isinstance(raw_messages, Mapping):
            raw_messages = [raw_messages]
        if not isinstance(raw_messages, Iterable):
            raise TypeError(f"Messages placeholder must be iterable: {self.variable_name}")
        return normalize_messages(raw_messages)


class ChatPromptTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parts: list[MessageTemplate | MessagesPlaceholder | LLMMessage]

    @classmethod
    def from_messages(cls, parts: Iterable[PromptPart]) -> "ChatPromptTemplate":
        normalized_parts: list[MessageTemplate | MessagesPlaceholder | LLMMessage] = []
        for part in parts:
            if isinstance(part, (MessageTemplate, MessagesPlaceholder, LLMMessage)):
                normalized_parts.append(part)
            elif isinstance(part, tuple):
                role, template = part
                normalized_parts.append(
                    MessageTemplate.from_template(role, template)  # type: ignore[arg-type]
                )
            elif isinstance(part, str):
                normalized_parts.append(MessageTemplate.from_template("user", part))
            else:
                raise TypeError(f"Unsupported prompt part: {type(part).__name__}")
        return cls(parts=normalized_parts)

    def render_messages(self, **values: Any) -> list[LLMMessage]:
        messages: list[LLMMessage] = []
        for part in self.parts:
            if isinstance(part, MessageTemplate):
                messages.append(part.render(values))
            elif isinstance(part, MessagesPlaceholder):
                messages.extend(part.render(values))
            else:
                messages.append(part)
        return messages

    def request(
        self,
        *,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        response_format: Literal["text", "json_object"] = "text",
        metadata: dict[str, Any] | None = None,
        **values: Any,
    ) -> LLMRequest:
        return LLMRequest(
            messages=self.render_messages(**values),
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            response_format=response_format,
            metadata=metadata or {},
        )

