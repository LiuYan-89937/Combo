from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


RuntimeErrorCategory = Literal[
    "cancelled",
    "timeout",
    "approval_denied",
    "dependency",
    "provider",
    "tool",
    "mcp",
    "validation",
    "conflict",
    "unavailable",
    "internal",
]
RuntimeTerminalStatus = Literal["failed", "cancelled"]


class RuntimeErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    category: RuntimeErrorCategory
    terminal_status: RuntimeTerminalStatus
    retryable: bool = False
    user_message_key: str
    diagnostic_ref: str | None = None
    request_id: str
    runtime_instance_id: str
    operation: str
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "code",
        "user_message_key",
        "request_id",
        "runtime_instance_id",
        "operation",
    )
    @classmethod
    def _required_text(cls, value: str, info: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{info.field_name} must not be empty")
        return text

    @field_validator("diagnostic_ref")
    @classmethod
    def _optional_text(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None
