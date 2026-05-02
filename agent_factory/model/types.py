from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class LLMMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None
    tool_call_id: str | None = None


class SystemMessage(LLMMessage):
    role: Literal["system"] = "system"


class UserMessage(LLMMessage):
    role: Literal["user"] = "user"


class HumanMessage(UserMessage):
    """LangChain-style alias for user messages."""


class AssistantMessage(LLMMessage):
    role: Literal["assistant"] = "assistant"


class AIMessage(AssistantMessage):
    """LangChain-style alias for assistant messages."""


class ToolMessage(LLMMessage):
    role: Literal["tool"] = "tool"
    tool_call_id: str


class ToolCallProposal(BaseModel):
    """A model-proposed tool call.

    The proposal is never executed by the model adapter. Runtime and ToolRouter decide
    whether the tool may run.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class ModelError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    message: str
    status_code: int | None = None
    retryable: bool = False
    provider_error_code: str | None = None


class LLMRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[LLMMessage]
    temperature: float | None = None
    max_output_tokens: int | None = None
    response_format: Literal["text", "json_object"] = "text"
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = ""
    provider: str
    model: str | None = None
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    tool_call_proposals: list[ToolCallProposal] = Field(default_factory=list)
    error: ModelError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class LLMStreamEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["started", "delta", "tool_call_delta", "completed", "error"]
    delta: str | None = None
    response: LLMResponse | None = None
    error: ModelError | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class StructuredOutputResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: Mapping[str, Any] | list[Any] | None = None
    response: LLMResponse
    error: ModelError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None
