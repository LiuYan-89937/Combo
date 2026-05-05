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
from agent_factory.factory_context import (
    CapabilityPlan,
    ConditionPlan,
    EvidenceReport,
    FactoryContextEnvelope,
    ImplementationPlan,
    ProductionSummary,
    ReadinessDecision,
    RequirementUnderstanding,
    ResourceContractSet,
    ResourceNeedPlan,
)
from agent_factory.specs import AgentPackagePrimitives, ValidationReport
from agent_factory.specs import EnvironmentProbeReport, ReadinessReport, ResourceContractsSpec

ProductionStatus = Literal[
    "running",
    "completed",
    "completed_with_warnings",
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
    tool_precondition_report: dict[str, Any] | None
    web_research_report: dict[str, Any] | None
    research_brief_report: dict[str, Any] | None
    research_completeness_report: dict[str, Any] | None
    requirement_understanding: dict[str, Any] | None
    capability_plan: dict[str, Any] | None
    condition_plan: dict[str, Any] | None
    resource_need_plan: dict[str, Any] | None
    evidence_reports: list[dict[str, Any]]
    resource_contract_set: dict[str, Any] | None
    readiness_decision: dict[str, Any] | None
    implementation_plan: dict[str, Any] | None
    production_summary: dict[str, Any] | None
    context_envelopes: list[dict[str, Any]]
    decision_records: list[dict[str, Any]]
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
    tool_precondition_report: dict[str, Any] | None = None
    web_research_report: dict[str, Any] | None = None
    research_brief_report: dict[str, Any] | None = None
    research_completeness_report: dict[str, Any] | None = None
    requirement_understanding: RequirementUnderstanding | None = None
    capability_plan: CapabilityPlan | None = None
    condition_plan: ConditionPlan | None = None
    resource_need_plan: ResourceNeedPlan | None = None
    evidence_reports: list[EvidenceReport] = Field(default_factory=list)
    resource_contract_set: ResourceContractSet | None = None
    readiness_decision: ReadinessDecision | None = None
    implementation_plan: ImplementationPlan | None = None
    production_summary: ProductionSummary | None = None
    context_envelopes: list[FactoryContextEnvelope] = Field(default_factory=list)
    decision_records: list[dict[str, Any]] = Field(default_factory=list)
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
