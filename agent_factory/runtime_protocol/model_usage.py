from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import Field, field_validator

from agent_factory.runtime_protocol.contracts import FrozenProtocolModel, utc_now_text


class RuntimeModelUsage(FrozenProtocolModel):
    usage_id: str = Field(default_factory=lambda: uuid4().hex)
    observation_event_id: str
    principal_id: str
    request_id: str
    runtime_instance_id: str
    attempt_id: str
    session_id: str
    turn_id: str
    workspace_id: str
    task_revision: int = Field(ge=1)
    runtime_role: Literal["main", "temporary"]
    strategy: Literal["react", "plan_and_execute"]
    node_id: str
    model_operation: Literal["main_turn", "temporary_turn"]
    model_profile_id: str
    model_profile_revision: int = Field(ge=1)
    provider: str
    model_name: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    reasoning_tokens: int = Field(ge=0)
    cache_read_tokens: int = Field(ge=0)
    cache_write_tokens: int = Field(ge=0)
    usage_source: Literal[
        "provider_usage",
        "provider_usage_with_fallback",
        "local_estimation",
    ] = "provider_usage"
    created_at: str = Field(default_factory=utc_now_text)

    @field_validator(
        "usage_id",
        "observation_event_id",
        "principal_id",
        "request_id",
        "runtime_instance_id",
        "attempt_id",
        "session_id",
        "turn_id",
        "workspace_id",
        "node_id",
        "model_profile_id",
        "provider",
        "model_name",
        "created_at",
    )
    @classmethod
    def _required_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{getattr(info, 'field_name', 'value')} must not be empty")
        return text
