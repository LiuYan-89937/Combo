from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import uuid4

from pydantic import Field, JsonValue, field_validator, model_validator

from combo.runtime_protocol.contracts import AttachmentRevisionRef, FrozenProtocolModel, ProtocolModel, utc_now_text


ConversationRole = Literal["user", "assistant", "tool"]
ConversationMessageStatus = Literal["pending", "committed", "cancelled"]
ConversationTurnStatus = Literal[
    "queued",
    "running",
    "waiting_approval",
    "waiting_external",
    "completed",
    "failed",
    "cancelled",
]


class TextPart(FrozenProtocolModel):
    kind: Literal["text"] = "text"
    text: str

    @field_validator("text")
    @classmethod
    def _text_is_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("text part must not be empty")
        return text


class ReasoningPart(FrozenProtocolModel):
    kind: Literal["reasoning"] = "reasoning"
    text: str

    @field_validator("text")
    @classmethod
    def _text_is_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("reasoning part must not be empty")
        return text


class AttachmentPart(FrozenProtocolModel):
    kind: Literal["attachment"] = "attachment"
    attachment: AttachmentRevisionRef


class ArtifactPart(FrozenProtocolModel):
    kind: Literal["artifact"] = "artifact"
    artifact_id: str
    revision: int = Field(ge=1)

    @field_validator("artifact_id")
    @classmethod
    def _artifact_id_is_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("artifact_id must not be empty")
        return text


class ToolCallPart(FrozenProtocolModel):
    kind: Literal["tool_call"] = "tool_call"
    tool_call_id: str
    capability_id: str
    capability_revision: int = Field(ge=1)
    model_alias: str
    arguments: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("tool_call_id", "capability_id", "model_alias")
    @classmethod
    def _tool_call_text_is_present(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text


class ToolResultPart(FrozenProtocolModel):
    kind: Literal["tool_result"] = "tool_result"
    tool_call_id: str
    status: Literal["completed", "failed", "cancelled", "rejected", "timed_out"]
    output: dict[str, JsonValue] | None = None
    error_code: str | None = None
    started_at: str | None = None
    completed_at: str | None = None

    @field_validator("tool_call_id")
    @classmethod
    def _tool_call_id_is_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("tool_call_id must not be empty")
        return text

    @field_validator("error_code", "started_at", "completed_at")
    @classmethod
    def _optional_error_code(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @model_validator(mode="after")
    def _result_is_explicit(self) -> "ToolResultPart":
        if self.status == "completed":
            if self.output is None or self.error_code is not None:
                raise ValueError("completed tool result requires output and no error_code")
        elif self.error_code is None:
            raise ValueError(f"{self.status} tool result requires error_code")
        return self


class DiagnosticPart(FrozenProtocolModel):
    kind: Literal["diagnostic"] = "diagnostic"
    diagnostic_ref: str
    user_message_key: str

    @field_validator("diagnostic_ref", "user_message_key")
    @classmethod
    def _diagnostic_text_is_present(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text


ConversationPart = Annotated[
    Union[TextPart, ReasoningPart, AttachmentPart, ArtifactPart, ToolCallPart, ToolResultPart, DiagnosticPart],
    Field(discriminator="kind"),
]


class ConversationMessage(ProtocolModel):
    message_id: str = Field(default_factory=lambda: uuid4().hex)
    session_id: str
    turn_id: str
    role: ConversationRole
    status: ConversationMessageStatus = "pending"
    parts: tuple[ConversationPart, ...]
    source_runtime_instance_id: str | None = None
    source_request_id: str | None = None
    source_task_revision: int | None = Field(default=None, ge=1)
    created_at: str = Field(default_factory=utc_now_text)
    committed_at: str | None = None
    visibility: Literal["public", "internal"] = "public"
    notification_event_ids: tuple[str, ...] = ()
    completion_reason: Literal["user_interrupted"] | None = None

    @field_validator("message_id", "session_id", "turn_id")
    @classmethod
    def _required_message_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @field_validator("source_runtime_instance_id", "source_request_id", "committed_at")
    @classmethod
    def _optional_message_text(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @field_validator("notification_event_ids")
    @classmethod
    def _notification_event_ids_are_stable(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(dict.fromkeys(str(item or "").strip() for item in value))
        if any(not item for item in normalized):
            raise ValueError("notification_event_ids must not contain empty values")
        return normalized

    @model_validator(mode="after")
    def _message_is_consistent(self) -> "ConversationMessage":
        if not self.parts:
            raise ValueError("conversation message requires at least one part")
        committed = self.status == "committed"
        if committed != bool(self.committed_at):
            raise ValueError("committed message status and committed_at must be set together")
        source_fields = (
            self.source_runtime_instance_id,
            self.source_request_id,
            self.source_task_revision,
        )
        if self.role == "user" and any(item is not None for item in source_fields):
            raise ValueError("user message cannot be attributed to a runtime instance")
        if self.role != "user" and any(item is None for item in source_fields):
            raise ValueError("assistant and tool messages require complete runtime attribution")
        if self.notification_event_ids and (self.role != "user" or self.visibility != "internal"):
            raise ValueError("notification_event_ids require an internal user message")
        if self.completion_reason is not None and self.role != "assistant":
            raise ValueError("completion_reason is only valid for assistant messages")
        return self


class ConversationTurn(ProtocolModel):
    turn_id: str = Field(default_factory=lambda: uuid4().hex)
    session_id: str
    user_message_id: str
    task_revision: int = Field(ge=1)
    status: ConversationTurnStatus = "queued"
    active_runtime_instance_id: str | None = None
    source_command_id: str | None = None
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = Field(default_factory=utc_now_text)
    terminal_at: str | None = None

    @field_validator("turn_id", "session_id", "user_message_id")
    @classmethod
    def _required_turn_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @field_validator("active_runtime_instance_id", "source_command_id", "terminal_at")
    @classmethod
    def _optional_turn_text(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @model_validator(mode="after")
    def _turn_terminal_is_consistent(self) -> "ConversationTurn":
        terminal = self.status in {"completed", "failed", "cancelled"}
        if terminal != bool(self.terminal_at):
            raise ValueError("terminal turn status and terminal_at must be set together")
        return self


class ContextSummary(FrozenProtocolModel):
    summary_id: str = Field(default_factory=lambda: uuid4().hex)
    session_id: str
    source_message_ids: tuple[str, ...]
    source_digest: str
    summary: str
    created_at: str = Field(default_factory=utc_now_text)

    @field_validator("summary_id", "session_id", "source_digest", "summary")
    @classmethod
    def _required_summary_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @field_validator("source_message_ids")
    @classmethod
    def _source_messages_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(str(value or "").strip() for value in values)
        if not normalized or any(not value for value in normalized):
            raise ValueError("context summary requires non-empty source message ids")
        if len(normalized) != len(set(normalized)):
            raise ValueError("context summary source message ids must be unique")
        return normalized
