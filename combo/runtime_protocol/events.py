from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import uuid4

from pydantic import Field, JsonValue, field_validator, model_validator

from combo.runtime_protocol.contracts import (
    CapabilitySelection,
    FrozenProtocolModel,
    RuntimeInstanceStatus,
    RuntimeRole,
    TaskRevisionAction,
    utc_now_text,
)
from combo.runtime_protocol.errors import RuntimeErrorEnvelope
from combo.runtime_protocol.conversation import ConversationPart
from combo.runtime_protocol.tool_calls import ToolCallStatus


class RuntimeLifecyclePayload(FrozenProtocolModel):
    kind: Literal[
        "runtime_created",
        "runtime_queued",
        "runtime_started",
        "runtime_recovered",
        "runtime_cancelling",
    ]
    status: RuntimeInstanceStatus


class AssistantMessageSnapshot(FrozenProtocolModel):
    message_id: str
    parts: tuple[ConversationPart, ...]
    created_at: str

    @field_validator("message_id", "created_at")
    @classmethod
    def _required_message_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @field_validator("parts")
    @classmethod
    def _message_has_parts(cls, value: tuple[ConversationPart, ...]) -> tuple[ConversationPart, ...]:
        if not value:
            raise ValueError("assistant message snapshot requires at least one part")
        return value


class RuntimeCompletedPayload(FrozenProtocolModel):
    kind: Literal["runtime_completed"] = "runtime_completed"
    status: Literal["completed"] = "completed"
    result: JsonValue | None = None
    message: AssistantMessageSnapshot | None = None
    context_window: dict[str, JsonValue] | None = None


class RuntimeWaitingPayload(FrozenProtocolModel):
    kind: Literal["runtime_waiting_approval", "runtime_waiting_external"]
    status: Literal["waiting_approval", "waiting_external"]
    details: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _kind_matches_status(self) -> "RuntimeWaitingPayload":
        expected = f"runtime_{self.status}"
        if self.kind != expected:
            raise ValueError("runtime waiting event kind does not match status")
        return self


class CapabilityResolutionStartedPayload(FrozenProtocolModel):
    kind: Literal["capability_resolution_started"] = "capability_resolution_started"
    requirements: tuple[str, ...] = ()

    @field_validator("requirements")
    @classmethod
    def _requirements_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(str(value or "").strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("capability requirements must not be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("capability requirements must be unique")
        return normalized


class CapabilitySelectionPayload(FrozenProtocolModel):
    kind: Literal["capability_selected", "capability_rejected"]
    selection: CapabilitySelection

    @model_validator(mode="after")
    def _kind_matches_selection(self) -> "CapabilitySelectionPayload":
        expected = "capability_selected" if self.selection.status == "selected" else "capability_rejected"
        if self.kind != expected:
            raise ValueError("capability event kind does not match selection status")
        return self


class CapabilitySnapshotCreatedPayload(FrozenProtocolModel):
    kind: Literal["capability_snapshot_created"] = "capability_snapshot_created"
    capability_snapshot_id: str
    content_digest: str

    @field_validator("capability_snapshot_id", "content_digest")
    @classmethod
    def _required_snapshot_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text


class DependencyEnvironmentPayload(FrozenProtocolModel):
    kind: Literal["dependency_environment_requested", "dependency_environment_ready"]
    dependency_environment_id: str
    dependency_digest: str

    @field_validator("dependency_environment_id", "dependency_digest")
    @classmethod
    def _required_dependency_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text


class TemporaryAgentStartedPayload(FrozenProtocolModel):
    kind: Literal["temporary_agent_started"] = "temporary_agent_started"
    child_runtime_instance_id: str
    task_id: str

    @field_validator("child_runtime_instance_id", "task_id")
    @classmethod
    def _required_child_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text


class TaskRevisionChangedPayload(FrozenProtocolModel):
    kind: Literal["task_revision_changed"] = "task_revision_changed"
    revision: int = Field(ge=1)
    action: TaskRevisionAction
    user_message_id: str

    @field_validator("user_message_id")
    @classmethod
    def _required_message_id(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("user_message_id must not be empty")
        return text


class ProgressPayload(FrozenProtocolModel):
    kind: Literal["progress"] = "progress"
    stage_id: str
    message: str
    completed_units: int | None = Field(default=None, ge=0)
    total_units: int | None = Field(default=None, ge=1)

    @field_validator("stage_id", "message")
    @classmethod
    def _required_progress_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @model_validator(mode="after")
    def _progress_units_are_consistent(self) -> "ProgressPayload":
        if (self.completed_units is None) != (self.total_units is None):
            raise ValueError("progress units must be set together")
        if self.completed_units is not None and self.completed_units > self.total_units:
            raise ValueError("completed_units cannot exceed total_units")
        return self


class QuestionPayload(FrozenProtocolModel):
    kind: Literal["question"] = "question"
    question_id: str
    prompt: str

    @field_validator("question_id", "prompt")
    @classmethod
    def _required_question_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text


class ApprovalRequiredPayload(FrozenProtocolModel):
    kind: Literal["approval_required"] = "approval_required"
    interrupt_id: str
    tool_call_id: str
    capability_id: str
    summary: str

    @field_validator("interrupt_id", "tool_call_id", "capability_id", "summary")
    @classmethod
    def _required_approval_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text


class ToolLifecyclePayload(FrozenProtocolModel):
    kind: Literal["tool_started", "tool_progress", "tool_completed", "tool_failed", "tool_cancelled"]
    tool_call_id: str
    capability_id: str
    status: ToolCallStatus
    progress_message: str | None = None
    output: dict[str, JsonValue] | None = None
    error_code: str | None = None

    @field_validator("tool_call_id", "capability_id")
    @classmethod
    def _required_tool_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @field_validator("progress_message", "error_code")
    @classmethod
    def _optional_tool_text(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None


class ArtifactPayload(FrozenProtocolModel):
    kind: Literal["artifact"] = "artifact"
    artifact_id: str
    revision: int = Field(ge=1)
    title: str
    media_type: str

    @field_validator("artifact_id", "title", "media_type")
    @classmethod
    def _required_artifact_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text


class ResultPayload(FrozenProtocolModel):
    kind: Literal["result"] = "result"
    content: str
    artifact_ids: tuple[str, ...] = ()
    structured: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def _required_result_content(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("result content must not be empty")
        return text


class TerminalErrorPayload(FrozenProtocolModel):
    kind: Literal["failed", "cancelled"]
    error: RuntimeErrorEnvelope

    @model_validator(mode="after")
    def _kind_matches_error(self) -> "TerminalErrorPayload":
        if self.kind != self.error.terminal_status:
            raise ValueError("terminal event kind does not match error terminal status")
        return self


RuntimeEventPayload = Annotated[
    Union[
        RuntimeLifecyclePayload,
        RuntimeCompletedPayload,
        RuntimeWaitingPayload,
        CapabilityResolutionStartedPayload,
        CapabilitySelectionPayload,
        CapabilitySnapshotCreatedPayload,
        DependencyEnvironmentPayload,
        TemporaryAgentStartedPayload,
        TaskRevisionChangedPayload,
        ProgressPayload,
        QuestionPayload,
        ApprovalRequiredPayload,
        ToolLifecyclePayload,
        ArtifactPayload,
        ResultPayload,
        TerminalErrorPayload,
    ],
    Field(discriminator="kind"),
]


class RuntimeEvent(FrozenProtocolModel):
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    stream_id: str
    sequence: int = Field(ge=1)
    session_sequence: int = Field(ge=1)
    runtime_instance_id: str
    request_id: str
    session_id: str
    turn_id: str
    workspace_id: str
    task_revision: int = Field(ge=1)
    runtime_role: RuntimeRole | None = None
    task_id: str | None = None
    attempt_id: str | None = None
    payload: RuntimeEventPayload
    created_at: str = Field(default_factory=utc_now_text)

    @field_validator(
        "event_id",
        "stream_id",
        "runtime_instance_id",
        "request_id",
        "session_id",
        "turn_id",
        "workspace_id",
    )
    @classmethod
    def _required_event_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @field_validator("attempt_id", "task_id")
    @classmethod
    def _optional_event_text(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None
