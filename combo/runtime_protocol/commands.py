from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field, field_validator, model_validator

from combo.runtime_protocol.contracts import (
    ApprovalMode,
    AttachmentRevisionRef,
    ExecutionPreference,
    FrozenProtocolModel,
    ProtocolModel,
    utc_now_text,
)
from combo.runtime_protocol.errors import RuntimeErrorEnvelope
from combo.runtime_protocol.versioning import RUNTIME_PROTOCOL_VERSION


CommandStatus = Literal[
    "received",
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
    "rejected",
]
TerminalCommandStatus = Literal["completed", "failed", "cancelled", "rejected"]


class SendMessagePayload(FrozenProtocolModel):
    kind: Literal["send_message"] = "send_message"
    message_id: str
    content: str
    attachments: tuple[AttachmentRevisionRef, ...] = ()
    execution_preference: ExecutionPreference | None = None
    approval_mode: ApprovalMode | None = None
    force_collaboration: bool = False
    visibility: Literal["public", "internal"] = "public"
    notification_event_ids: tuple[str, ...] = ()
    scheduler_run_id: str | None = None

    @field_validator("message_id", "content")
    @classmethod
    def _required_message_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @field_validator("notification_event_ids")
    @classmethod
    def _notification_event_ids_are_stable(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(dict.fromkeys(str(item or "").strip() for item in value))
        if any(not item for item in normalized):
            raise ValueError("notification_event_ids must not contain empty values")
        return normalized

    @field_validator("scheduler_run_id")
    @classmethod
    def _optional_scheduler_run_id(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @model_validator(mode="after")
    def _internal_notification_identity_is_consistent(self) -> "SendMessagePayload":
        if self.notification_event_ids and self.visibility != "internal":
            raise ValueError("notification_event_ids require internal message visibility")
        if self.scheduler_run_id is not None and self.visibility != "internal":
            raise ValueError("scheduler_run_id requires internal message visibility")
        return self


class SetExecutionPreferencePayload(FrozenProtocolModel):
    kind: Literal["set_execution_preference"] = "set_execution_preference"
    execution_preference: ExecutionPreference
    approval_mode: ApprovalMode
    expected_policy_revision: int = Field(ge=1)


class CancelRuntimeRequestPayload(FrozenProtocolModel):
    kind: Literal["cancel_runtime_request"] = "cancel_runtime_request"
    runtime_instance_id: str
    request_id: str
    reason: str

    @field_validator("runtime_instance_id", "request_id", "reason")
    @classmethod
    def _required_cancel_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text


class CancelCommandRequestPayload(FrozenProtocolModel):
    kind: Literal["cancel_command_request"] = "cancel_command_request"
    target_command_id: str
    reason: str

    @field_validator("target_command_id", "reason")
    @classmethod
    def _required_cancel_command_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text


class ResumeInterruptPayload(FrozenProtocolModel):
    kind: Literal["resume_interrupt"] = "resume_interrupt"
    runtime_instance_id: str
    request_id: str
    interrupt_id: str
    decision: Literal["approve", "deny", "trust_tool", "revise", "answer"]
    response: str | None = None

    @field_validator("runtime_instance_id", "request_id", "interrupt_id")
    @classmethod
    def _required_interrupt_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @field_validator("response")
    @classmethod
    def _optional_response(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @model_validator(mode="after")
    def _response_matches_decision(self) -> "ResumeInterruptPayload":
        if self.decision in {"answer", "revise"} and self.response is None:
            raise ValueError(f"{self.decision} interrupt decision requires response")
        if self.decision not in {"answer", "revise"} and self.response is not None:
            raise ValueError(f"{self.decision} interrupt decision cannot carry response")
        return self


class SteerRuntimeRequestPayload(FrozenProtocolModel):
    kind: Literal["steer_runtime_request"] = "steer_runtime_request"
    queued_command_id: str

    @field_validator("queued_command_id")
    @classmethod
    def _required_queued_command_id(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("queued_command_id must not be empty")
        return text


CommandPayload = Annotated[
    Union[
        SendMessagePayload,
        SetExecutionPreferencePayload,
        CancelCommandRequestPayload,
        CancelRuntimeRequestPayload,
        ResumeInterruptPayload,
        SteerRuntimeRequestPayload,
    ],
    Field(discriminator="kind"),
]


class CommandEnvelope(FrozenProtocolModel):
    protocol_version: str = RUNTIME_PROTOCOL_VERSION
    command_id: str
    client_instance_id: str
    principal_id: str
    session_id: str
    payload: CommandPayload
    submitted_at: str = Field(default_factory=utc_now_text)

    @field_validator(
        "protocol_version",
        "command_id",
        "client_instance_id",
        "principal_id",
        "session_id",
    )
    @classmethod
    def _required_envelope_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text


class CommandReceipt(ProtocolModel):
    command_id: str
    client_instance_id: str
    principal_id: str
    session_id: str
    status: CommandStatus
    receipt_revision: int = Field(default=1, ge=1)
    request_id: str | None = None
    runtime_instance_id: str | None = None
    error: RuntimeErrorEnvelope | None = None
    rejection_code: str | None = None
    received_at: str = Field(default_factory=utc_now_text)
    updated_at: str = Field(default_factory=utc_now_text)
    terminal_at: str | None = None

    @field_validator("command_id", "client_instance_id", "principal_id", "session_id")
    @classmethod
    def _required_receipt_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @field_validator("request_id", "runtime_instance_id", "terminal_at", "rejection_code")
    @classmethod
    def _optional_receipt_text(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @model_validator(mode="after")
    def _terminal_state_is_consistent(self) -> "CommandReceipt":
        terminal = self.status in {"completed", "failed", "cancelled", "rejected"}
        if terminal != bool(self.terminal_at):
            raise ValueError("terminal command status and terminal_at must be set together")
        if self.status == "failed" and self.error is None:
            raise ValueError("failed command receipt requires error")
        if self.status == "rejected" and self.rejection_code is None:
            raise ValueError("rejected command receipt requires rejection_code")
        if self.status != "rejected" and self.rejection_code is not None:
            raise ValueError("only rejected command receipt can carry rejection_code")
        if self.error is not None:
            if self.error.request_id != self.request_id:
                raise ValueError("command error request identity does not match receipt")
            if self.error.runtime_instance_id != self.runtime_instance_id:
                raise ValueError("command error runtime identity does not match receipt")
        return self
