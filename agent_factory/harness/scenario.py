from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.specs import Metadata


class HarnessTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    user: str
    assistant: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResponseConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    must_include: list[str] = Field(default_factory=list)
    must_not_include: list[str] = Field(default_factory=list)


class ScenarioExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    intent: str | None = None
    expected_intent: str | None = None
    expected_runtime_type: str | None = None
    expected_runtime_path: list[str] = Field(default_factory=list)
    expected_route_decision: str | None = None
    selected_tool: str | None = None
    expected_selected_tool: str | None = None
    expected_mcp_call: str | None = None
    forbidden_tools: list[str] = Field(default_factory=list)
    forbidden_mcp_calls: list[str] = Field(default_factory=list)
    must_confirm: bool | None = None
    forbidden_direct_execution: bool = False
    context_visibility: dict[str, Any] = Field(default_factory=dict)
    memory_read_allowed: bool | None = None
    memory_write_allowed: bool | None = None
    response_constraints: ResponseConstraints = Field(default_factory=ResponseConstraints)
    upgrade_request_expected: bool | None = None

    @property
    def selected_tool_id(self) -> str | None:
        return self.selected_tool or self.expected_selected_tool

    @property
    def intent_id(self) -> str | None:
        return self.intent or self.expected_intent


class ObservationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    trace: bool = False
    runtime_path: bool = False
    route_decisions: bool = False
    context_bundle: bool = False
    tool_calls: bool = False
    mcp_calls: bool = False
    memory_ops: bool = False
    final_response: bool = False
    interrupts: bool = False


class HarnessScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: str
    name: str | None = None
    description: str | None = None
    turns: list[HarnessTurn]
    fixtures: list[str] = Field(default_factory=list)
    expected: ScenarioExpectation
    observe: ObservationSpec


class FixtureSpec(BaseModel):
    model_config = ConfigDict(extra="allow", validate_assignment=True)

    mode: Literal["mock", "real", "disabled"] = "mock"
    output: Any = None


class HarnessFixtures(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    tools: dict[str, FixtureSpec] = Field(default_factory=dict)
    mcp: dict[str, FixtureSpec] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    memory: dict[str, Any] = Field(default_factory=dict)


class HarnessObservationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    trace: bool = True
    runtime_path: bool = True
    route_decisions: bool = True
    context_bundle: bool = True
    tool_calls: bool = True
    mcp_calls: bool = True
    memory_ops: bool = True
    final_response: bool = True


class HarnessSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    schema_version: str
    kind: Literal["HarnessSpec"] = "HarnessSpec"
    metadata: Metadata
    observation: HarnessObservationPolicy = Field(default_factory=HarnessObservationPolicy)
    fixtures: HarnessFixtures = Field(default_factory=HarnessFixtures)
    scenarios: list[HarnessScenario]
