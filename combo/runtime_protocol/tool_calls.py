from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ToolCallStatus = Literal[
    "proposed",
    "waiting_approval",
    "running",
    "completed",
    "failed",
    "cancelled",
    "rejected",
    "timed_out",
]
TERMINAL_TOOL_CALL_STATUSES = frozenset({"completed", "failed", "cancelled", "rejected", "timed_out"})


class ToolCallRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_call_id: str
    runtime_instance_id: str
    request_id: str
    turn_id: str
    attempt_id: str
    capability_id: str
    capability_revision: int = Field(ge=1)
    model_alias: str
    display_alias: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: ToolCallStatus = "proposed"
    result: dict[str, Any] | None = None
    error_code: str | None = None
    created_at: str
    updated_at: str
    started_at: str | None = None
    completed_at: str | None = None

    @field_validator(
        "tool_call_id",
        "runtime_instance_id",
        "request_id",
        "turn_id",
        "attempt_id",
        "capability_id",
        "model_alias",
        "created_at",
        "updated_at",
    )
    @classmethod
    def _required_text(cls, value: str, info: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{info.field_name} must not be empty")
        return text

    @field_validator("error_code")
    @classmethod
    def _optional_text(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @field_validator("display_alias")
    @classmethod
    def _optional_display_alias(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @field_validator("started_at", "completed_at")
    @classmethod
    def _optional_timestamp(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @model_validator(mode="after")
    def _terminal_result_is_explicit(self) -> "ToolCallRecord":
        if self.status not in TERMINAL_TOOL_CALL_STATUSES:
            if self.result is not None or self.error_code is not None:
                raise ValueError("non-terminal tool call cannot carry result or error_code")
            return self
        if self.status == "completed":
            if self.result is None:
                raise ValueError("completed tool call requires result")
            if self.error_code is not None:
                raise ValueError("completed tool call cannot carry error_code")
            return self
        if self.error_code is None:
            raise ValueError(f"{self.status} tool call requires error_code")
        return self
