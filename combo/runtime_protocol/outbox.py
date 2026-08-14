from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import Field, JsonValue, field_validator, model_validator

from combo.runtime_protocol.contracts import ProtocolModel, utc_now_text


OutboxStatus = Literal["pending", "publishing", "published", "failed", "dead_letter"]


class OutboxRecord(ProtocolModel):
    outbox_id: str = Field(default_factory=lambda: uuid4().hex)
    aggregate_kind: Literal[
        "conversation",
        "runtime_instance",
        "command",
        "tool_call",
        "workspace",
        "delivery",
        "scheduler_run",
        "capability",
        "runtime_policy",
        "delegated_task",
    ]
    aggregate_id: str
    aggregate_revision: int = Field(ge=1)
    event_id: str
    event_kind: str
    payload: dict[str, JsonValue]
    status: OutboxStatus = "pending"
    publish_attempts: int = Field(default=0, ge=0)
    next_attempt_at: str | None = None
    published_at: str | None = None
    error_code: str | None = None
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = Field(default_factory=utc_now_text)

    @field_validator("outbox_id", "aggregate_id", "event_id", "event_kind")
    @classmethod
    def _required_outbox_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @field_validator("next_attempt_at", "published_at", "error_code")
    @classmethod
    def _optional_outbox_text(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @model_validator(mode="after")
    def _outbox_state_is_consistent(self) -> "OutboxRecord":
        if self.status == "published":
            if self.published_at is None or self.error_code is not None:
                raise ValueError("published outbox record requires published_at and no error_code")
        elif self.published_at is not None:
            raise ValueError("non-published outbox record cannot set published_at")
        if self.status in {"failed", "dead_letter"} and self.error_code is None:
            raise ValueError(f"{self.status} outbox record requires error_code")
        return self
