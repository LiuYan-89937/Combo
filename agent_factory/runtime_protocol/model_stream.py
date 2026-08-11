from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated, Literal, Protocol, Union

from pydantic import Field, JsonValue, field_validator

from agent_factory.runtime_protocol.contracts import FrozenProtocolModel


class TextDelta(FrozenProtocolModel):
    kind: Literal["text_delta"] = "text_delta"
    text: str


class ReasoningDelta(FrozenProtocolModel):
    kind: Literal["reasoning_delta"] = "reasoning_delta"
    text: str


class ToolCallStarted(FrozenProtocolModel):
    kind: Literal["tool_call_started"] = "tool_call_started"
    provider_tool_call_id: str
    model_alias: str

    @field_validator("provider_tool_call_id", "model_alias")
    @classmethod
    def _required_tool_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text


class ToolCallArgumentsDelta(FrozenProtocolModel):
    kind: Literal["tool_call_arguments_delta"] = "tool_call_arguments_delta"
    provider_tool_call_id: str
    json_fragment: str

    @field_validator("provider_tool_call_id")
    @classmethod
    def _required_provider_tool_call_id(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("provider_tool_call_id must not be empty")
        return text


class ToolCallCompleted(FrozenProtocolModel):
    kind: Literal["tool_call_completed"] = "tool_call_completed"
    provider_tool_call_id: str
    arguments: dict[str, JsonValue]

    @field_validator("provider_tool_call_id")
    @classmethod
    def _required_provider_tool_call_id(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("provider_tool_call_id must not be empty")
        return text


class ModelUsageCompleted(FrozenProtocolModel):
    kind: Literal["usage_completed"] = "usage_completed"
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)


class ModelStreamCompleted(FrozenProtocolModel):
    kind: Literal["stream_completed"] = "stream_completed"
    finish_reason: str

    @field_validator("finish_reason")
    @classmethod
    def _finish_reason_is_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("finish_reason must not be empty")
        return text


NormalizedModelStreamPayload = Annotated[
    Union[
        TextDelta,
        ReasoningDelta,
        ToolCallStarted,
        ToolCallArgumentsDelta,
        ToolCallCompleted,
        ModelUsageCompleted,
        ModelStreamCompleted,
    ],
    Field(discriminator="kind"),
]


class NormalizedModelStreamEvent(FrozenProtocolModel):
    operation_id: str
    attempt_id: str
    sequence: int = Field(ge=1)
    payload: NormalizedModelStreamPayload

    @field_validator("operation_id", "attempt_id")
    @classmethod
    def _required_stream_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text


class ModelStreamNormalizer(Protocol):
    def normalize(
        self,
        provider_chunks: Iterable[object],
        *,
        operation_id: str,
        attempt_id: str,
    ) -> Iterable[NormalizedModelStreamEvent]: ...
