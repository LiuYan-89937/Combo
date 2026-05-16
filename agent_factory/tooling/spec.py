from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


SNAKE_CASE_ID = re.compile(r"^[a-z][a-z0-9_]*$")

ToolObservationStatus = Literal[
    "denied",
    "revision_requested",
    "invalid_arguments",
    "invalid_output",
    "execution_failed",
    "completed",
]

ToolEventType = Literal[
    "tool_call_proposed",
    "tool_approval_requested",
    "tool_approval_resolved",
    "tool_call_started",
    "tool_call_completed",
    "tool_call_failed",
    "tool_observation_available",
]


class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    description: str
    entrypoint: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    resources: dict[str, str] = Field(default_factory=dict)
    approval_required: bool = False
    concurrent: bool = True

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not SNAKE_CASE_ID.fullmatch(value):
            raise ValueError("tool id must be snake_case")
        return value

    @field_validator("entrypoint")
    @classmethod
    def validate_entrypoint(cls, value: str) -> str:
        if ":" not in value:
            raise ValueError("entrypoint must use '<path_or_module>:<function>'")
        target, function = value.rsplit(":", 1)
        if not target.strip() or not function.strip():
            raise ValueError("entrypoint target and function must be non-empty")
        return value

    @field_validator("input_schema", "output_schema")
    @classmethod
    def validate_schema_object(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("schema must be a JSON object")
        return value

    @field_validator("resources")
    @classmethod
    def validate_resources(cls, value: dict[str, str]) -> dict[str, str]:
        for local_name, global_key in value.items():
            if not local_name or not global_key:
                raise ValueError("resource local names and global keys must be non-empty")
        return value


class ModelToolView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    approval_required: bool = False


class ToolObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["tool_observation"] = "tool_observation"
    status: ToolObservationStatus
    tool_id: str
    tool_call_id: str | None = None
    message: str
    user_instruction: str | None = None
    retryable: bool = True
    arguments: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)


class ToolEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_call_id: str | None = None
    tool_id: str
    node_id: str | None = None
    stage_id: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: str
    output: dict[str, Any] | None = None
    observation: dict[str, Any] | None = None
    message: str = ""


def model_tool_view(spec: ToolSpec) -> ModelToolView:
    return ModelToolView(
        id=spec.id,
        description=spec.description,
        input_schema=spec.input_schema,
        approval_required=spec.approval_required,
    )
