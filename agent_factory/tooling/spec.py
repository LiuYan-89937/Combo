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
ToolExecutionStatus = Literal["completed", "failed"]
ToolContractStatus = Literal["valid", "invalid"]

ToolRiskLevel = Literal["low", "medium", "high"]
ToolRiskAction = Literal["inherit", "allow", "ask", "deny", "uncertain"]
ToolLLMRiskMode = Literal["disabled", "on_uncertain", "always"]

ToolEventType = Literal[
    "tool_call_proposed",
    "tool_approval_requested",
    "tool_approval_resolved",
    "tool_call_started",
    "tool_call_completed",
    "tool_contract_invalid",
    "tool_call_failed",
    "tool_observation_available",
]


class ToolRiskEvaluatorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hard: str | None = None
    llm: str | None = None
    llm_mode: ToolLLMRiskMode = "disabled"


class ToolRiskContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str
    base_risk_level: ToolRiskLevel
    arguments: dict[str, Any] = Field(default_factory=dict)
    resources: dict[str, Any] = Field(default_factory=dict)
    tool_call: dict[str, Any] = Field(default_factory=dict)


class ToolRiskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ToolRiskAction = "inherit"
    risk_level: ToolRiskLevel | None = None
    reasons: list[str] = Field(default_factory=list)
    facts: dict[str, Any] = Field(default_factory=dict)
    normalized_arguments: dict[str, Any] | None = None


class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    description: str
    entrypoint: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    resources: dict[str, str] = Field(default_factory=dict)
    risk_level: ToolRiskLevel = "low"
    risk_evaluator: ToolRiskEvaluatorConfig = Field(default_factory=ToolRiskEvaluatorConfig)
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
        if value.startswith("mcp:"):
            target = value.removeprefix("mcp:")
            if "/" not in target:
                raise ValueError("MCP entrypoint must use 'mcp:<server_id>/<tool_name>'")
            server_id, tool_name = target.split("/", 1)
            if not server_id.strip() or not tool_name.strip():
                raise ValueError("MCP server_id and tool_name must be non-empty")
            return value
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
    risk_level: ToolRiskLevel = "low"


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
    output_ref: dict[str, Any] | None = None
    output_summary: str | None = None
    output_truncated: bool = False
    evidence: dict[str, Any] = Field(default_factory=dict)
    execution_status: ToolExecutionStatus = "failed"
    contract_status: ToolContractStatus = "valid"
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
    output_ref: dict[str, Any] | None = None
    output_summary: str | None = None
    output_truncated: bool = False
    evidence: dict[str, Any] = Field(default_factory=dict)
    execution_status: str = ""
    contract_status: str = ""
    observation: dict[str, Any] | None = None
    message: str = ""


def model_tool_view(spec: ToolSpec) -> ModelToolView:
    return ModelToolView(
        id=spec.id,
        description=spec.description,
        input_schema=spec.input_schema,
        risk_level=spec.risk_level,
    )
