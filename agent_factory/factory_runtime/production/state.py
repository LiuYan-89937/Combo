from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, TypedDict

from pydantic import ConfigDict, Field

from agent_factory.core import FactoryEvent
from agent_factory.core.types import JsonDumpMixin
from agent_factory.factory import FactoryError
from agent_factory.factory.package_verification import (
    FactoryVerificationReport,
    HarnessDryRunReport,
    MCPBindingLocalCheckReport,
    ToolStaticCheckReport,
    ToolTestRunReport,
)
from agent_factory.specs import AgentPackagePrimitives, ValidationReport
from agent_factory.specs import EnvironmentProbeReport, ReadinessReport, ResourceContractsSpec

ProductionStatus = Literal[
    "running",
    "completed",
    "failed",
    "needs_clarification",
    "not_agent_request",
]


class FactoryProductionStateDict(TypedDict, total=False):
    run_id: str
    requirement: str
    draft: bool
    status: ProductionStatus
    current_stage: str | None
    graph_node: str | None
    package_path: Path | None
    raw_model_data: dict[str, Any] | list[Any] | None
    primitives: AgentPackagePrimitives | None
    environment_report: EnvironmentProbeReport | None
    resource_contracts: ResourceContractsSpec | None
    readiness_report: ReadinessReport | None
    validation_report: ValidationReport | None
    generated_artifacts: list[Path]
    generated_tool_count: int
    generated_tool_test_count: int
    mcp_binding_count: int
    harness_scenario_count: int
    verification_report: FactoryVerificationReport | None
    tool_static_check_report: ToolStaticCheckReport | None
    tool_test_report: ToolTestRunReport | None
    mcp_binding_report: MCPBindingLocalCheckReport | None
    harness_dry_run_report: HarnessDryRunReport | None
    tool_test_repair_attempts: int
    max_tool_test_repair_attempts: int
    repair_attempts: int
    max_repair_attempts: int
    max_graph_steps: int
    clarification_questions: list[str]
    clarification_options: list[dict[str, Any]]
    factory_intent: dict[str, Any] | None
    guidance_message: str | None
    events: list[FactoryEvent]
    error: FactoryError | None
    requirement_analysis: dict[str, Any] | None
    runtime_type: str
    stage_history: list[str]


class FactoryProductionState(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    run_id: str
    requirement: str
    draft: bool = True
    status: ProductionStatus = "running"
    current_stage: str | None = None
    graph_node: str | None = None
    package_path: Path | None = None
    raw_model_data: dict[str, Any] | list[Any] | None = None
    primitives: AgentPackagePrimitives | None = None
    environment_report: EnvironmentProbeReport | None = None
    resource_contracts: ResourceContractsSpec | None = None
    readiness_report: ReadinessReport | None = None
    validation_report: ValidationReport | None = None
    generated_artifacts: list[Path] = Field(default_factory=list)
    generated_tool_count: int = 0
    generated_tool_test_count: int = 0
    mcp_binding_count: int = 0
    harness_scenario_count: int = 0
    verification_report: FactoryVerificationReport | None = None
    tool_static_check_report: ToolStaticCheckReport | None = None
    tool_test_report: ToolTestRunReport | None = None
    mcp_binding_report: MCPBindingLocalCheckReport | None = None
    harness_dry_run_report: HarnessDryRunReport | None = None
    tool_test_repair_attempts: int = 0
    max_tool_test_repair_attempts: int = 1
    repair_attempts: int = 0
    max_repair_attempts: int = 1
    max_graph_steps: int = 25
    clarification_questions: list[str] = Field(default_factory=list)
    clarification_options: list[dict[str, Any]] = Field(default_factory=list)
    factory_intent: dict[str, Any] | None = None
    guidance_message: str | None = None
    events: list[FactoryEvent] = Field(default_factory=list)
    error: FactoryError | None = None
    requirement_analysis: dict[str, Any] | None = None
    runtime_type: Literal["factory_production_langgraph"] = "factory_production_langgraph"
    stage_history: list[str] = Field(default_factory=list)

    def as_graph_state(self) -> FactoryProductionStateDict:
        return self.model_dump(mode="python", by_alias=True)  # type: ignore[return-value]

    @classmethod
    def from_graph_state(cls, state: FactoryProductionStateDict | dict[str, Any]) -> "FactoryProductionState":
        return cls.model_validate(dict(state))
