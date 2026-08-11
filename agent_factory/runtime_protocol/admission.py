from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from agent_factory.runtime_protocol.contracts import FrozenProtocolModel, ProtocolModel, utc_now_text


AdmissionResourceClass = Literal[
    "main_chat_model",
    "temporary_chat_model",
    "auxiliary_model",
    "embedding",
    "image_generation",
    "tool_process",
    "mcp",
    "dependency_build",
]
AdmissionStatus = Literal["queued", "granted", "released", "cancelled", "timed_out"]


class AdmissionRequest(FrozenProtocolModel):
    admission_request_id: str = Field(default_factory=lambda: uuid4().hex)
    resource_class: AdmissionResourceClass
    principal_id: str
    runtime_instance_id: str
    request_id: str
    operation_id: str
    priority: int = Field(default=0, ge=0)
    units: int = Field(default=1, ge=1)
    timeout_seconds: int = Field(ge=1)
    submitted_at: str = Field(default_factory=utc_now_text)

    @field_validator(
        "admission_request_id",
        "principal_id",
        "runtime_instance_id",
        "request_id",
        "operation_id",
    )
    @classmethod
    def _required_admission_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text


class AdmissionLease(ProtocolModel):
    admission_lease_id: str = Field(default_factory=lambda: uuid4().hex)
    request: AdmissionRequest
    application_generation: int = Field(ge=1)
    status: AdmissionStatus = "queued"
    queue_sequence: int = Field(ge=1)
    granted_at: str | None = None
    lease_expires_at: str | None = None
    terminal_at: str | None = None
    updated_at: str = Field(default_factory=utc_now_text)

    @field_validator("admission_lease_id")
    @classmethod
    def _lease_id_is_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("admission_lease_id must not be empty")
        return text

    @field_validator("granted_at", "lease_expires_at", "terminal_at")
    @classmethod
    def _optional_lease_text(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @model_validator(mode="after")
    def _lease_state_is_consistent(self) -> "AdmissionLease":
        if self.status == "granted":
            if not self.granted_at or not self.lease_expires_at or self.terminal_at:
                raise ValueError("granted admission lease requires grant and expiry without terminal_at")
        elif self.granted_at is not None or self.lease_expires_at is not None:
            raise ValueError("non-granted admission lease cannot retain active lease timestamps")
        terminal = self.status in {"released", "cancelled", "timed_out"}
        if terminal != bool(self.terminal_at):
            raise ValueError("terminal admission status and terminal_at must be set together")
        return self


class ModelOperation(FrozenProtocolModel):
    operation_id: str = Field(default_factory=lambda: uuid4().hex)
    runtime_instance_id: str
    request_id: str
    attempt_id: str
    provider_request_id: str | None = None
    profile_id: str
    profile_revision: int = Field(ge=1)
    credential_resource_id: str
    credential_revision: int = Field(ge=1)
    admission_request_id: str
    timeout_seconds: int = Field(ge=1)
    created_at: str = Field(default_factory=utc_now_text)

    @field_validator(
        "operation_id",
        "runtime_instance_id",
        "request_id",
        "attempt_id",
        "profile_id",
        "credential_resource_id",
        "admission_request_id",
    )
    @classmethod
    def _required_operation_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @field_validator("provider_request_id")
    @classmethod
    def _optional_provider_request_id(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None
