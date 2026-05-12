from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.assembly.schema import (
    AgentSpec,
    GraphOverrides,
    OutputSpec,
    RuntimeSpec,
    ToolSpec,
)


class CaptureIntentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal["chat", "inspect_factory", "manufacture_agent", "repair_agent", "unclear"]
    confidence: float = Field(ge=0, le=1)
    reason: str
    extracted_requirement: str | None = None
    reply_hint: str | None = None
    entry_stage: str | None = None
    should_run_graph: bool


class RequirementClarityOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_clear: bool
    confidence: float = Field(ge=0, le=1)
    reason: str
    missing_fields: list[str] = Field(default_factory=list, max_length=8)


class ClarificationOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    description: str | None = None


class ClarifyingQuestionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    question: str
    options: list[ClarificationOption] = Field(min_length=2, max_length=5)
    custom_option_id: str


class ClarifyingQuestionSetOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[ClarifyingQuestionOutput] = Field(min_length=1, max_length=5)


class RequirementMergeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_requirement: str
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=8)


class RuntimePatternAlternativeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern_id: str
    reason: str
    tradeoff: str | None = None


class RuntimePatternSelectionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_pattern_id: str
    selection_reason: str
    fit_summary: str
    alternatives: list[RuntimePatternAlternativeOutput] = Field(default_factory=list, max_length=5)
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    open_questions: list[str] = Field(default_factory=list, max_length=8)


class GraphBehaviorNodePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    node_type: str
    business_behavior: str
    input_expectation: str
    output_expectation: str
    user_visible: bool = False
    notes: list[str] = Field(default_factory=list, max_length=8)


class GraphBehaviorRoutePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_node: str
    to_node: str
    condition: str
    business_meaning: str
    expected_usage: str


class GraphBehaviorInterruptPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    business_reason: str
    user_visible_reason: str


class GraphBehaviorTerminationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success_nodes: list[str] = Field(default_factory=list)
    failure_nodes: list[str] = Field(default_factory=list)
    business_success_meaning: str
    business_failure_meaning: str


class GraphBehaviorPlanOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern_id: str
    pattern_name: str
    graph_intent: str
    nodes: list[GraphBehaviorNodePlan] = Field(default_factory=list)
    routes: list[GraphBehaviorRoutePlan] = Field(default_factory=list)
    interrupts: list[GraphBehaviorInterruptPlan] = Field(default_factory=list)
    termination: GraphBehaviorTerminationPlan
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    open_questions: list[str] = Field(default_factory=list, max_length=8)


class NodeWrapperPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wrapper_id: str
    phase: str
    purpose: str
    config: dict[str, object] = Field(default_factory=dict)
    config_notes: dict[str, str] = Field(default_factory=dict)


FactoryStrategyKind = Literal["context", "memory", "policy", "tool_visibility", "custom"]
FactoryStrategyPhase = Literal["before", "after", "around"]
FactoryStrategySource = Literal["catalog", "proposed"]


class NodeStrategyRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_id: str
    kind: FactoryStrategyKind
    phase: FactoryStrategyPhase
    purpose: str
    source: FactoryStrategySource = "catalog"
    config: dict[str, object] = Field(default_factory=dict)
    config_notes: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list, max_length=8)


class ProposedNodeStrategySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_id: str
    name: str
    description: str
    kind: FactoryStrategyKind
    phase: FactoryStrategyPhase
    required_by_node_ids: list[str] = Field(default_factory=list)
    applies_to_node_types: list[str] = Field(default_factory=list)
    reads: list[str] = Field(default_factory=list)
    writes: list[str] = Field(default_factory=list)
    config_schema: dict[str, object] = Field(default_factory=dict)
    implementation_notes: list[str] = Field(default_factory=list, max_length=8)


class NodeStrategyPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    node_type: str
    business_behavior_ref: str
    wrappers: list[NodeWrapperPlan] = Field(default_factory=list)
    strategy_refs: list[NodeStrategyRef] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    open_questions: list[str] = Field(default_factory=list, max_length=8)


class NodeStrategyPlanningOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern_id: str
    strategy_intent: str
    node_strategies: list[NodeStrategyPlan] = Field(default_factory=list)
    proposed_strategies: list[ProposedNodeStrategySpec] = Field(default_factory=list)
    global_assumptions: list[str] = Field(default_factory=list, max_length=8)
    open_questions: list[str] = Field(default_factory=list, max_length=8)


ToolCapabilityImplementationStatus = Literal[
    "available",
    "needs_generation",
    "needs_binding",
    "unknown",
]


class ToolCapabilitySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_id: str
    name: str
    description: str
    required_by_node_ids: list[str] = Field(default_factory=list)
    visible_to_node_ids: list[str] = Field(default_factory=list)
    approval_required: bool = False
    risk_notes: list[str] = Field(default_factory=list, max_length=8)
    input_contract: dict[str, object] = Field(default_factory=dict)
    output_contract: dict[str, object] = Field(default_factory=dict)
    implementation_status: ToolCapabilityImplementationStatus
    implementation_notes: list[str] = Field(default_factory=list, max_length=8)


class NodeToolVisibilitySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    allowed_tool_capability_ids: list[str] = Field(default_factory=list)
    approval_required_capability_ids: list[str] = Field(default_factory=list)
    blocked_tool_capability_ids: list[str] = Field(default_factory=list)
    reason: str


class ToolCapabilityPlanningOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_intent: str
    tool_capabilities: list[ToolCapabilitySpec] = Field(default_factory=list)
    node_tool_visibility: list[NodeToolVisibilitySpec] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    open_questions: list[str] = Field(default_factory=list, max_length=8)


ResourceCheckToolName = Literal[
    "file_read",
    "file_list",
    "file_exists",
    "search_files",
    "search_text",
    "shell_which",
    "shell_cwd",
    "shell_run",
]


class ResourceRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: str
    description: str
    required: bool = True
    used_by_capability_ids: list[str] = Field(default_factory=list)
    expected_resource_shape: dict[str, object] = Field(default_factory=dict)
    why_needed: str
    not_factory_resource_reason: str


class ResourceRequirementSetOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirements: list[ResourceRequirement] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list, max_length=8)


class ResourceCheckAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str
    requirement_id: str
    tool_name: ResourceCheckToolName
    arguments: dict[str, object] = Field(default_factory=dict)
    reason: str
    expected_evidence: str


class ResourceCheckPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: str
    checks: list[ResourceCheckAction] = Field(default_factory=list)
    uncheckable_reason: str | None = None


class ResourceCheckPlanOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plans: list[ResourceCheckPlan] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list, max_length=8)


class ResourceCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str
    requirement_id: str
    tool_name: ResourceCheckToolName
    status: Literal["completed", "error", "skipped"]
    result_summary: str
    raw_result: dict[str, object] = Field(default_factory=dict)


class ResourceReadinessAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    satisfied_requirements: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    uncertain_requirements: list[str] = Field(default_factory=list)
    blocked_requirements: list[str] = Field(default_factory=list)
    resource_value_hints: dict[str, str] = Field(default_factory=dict)
    reasons: dict[str, str] = Field(default_factory=dict)


class ResourceUserInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: str
    input_text: str


class ResourceRewriteOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resources: dict[str, object] = Field(default_factory=dict)
    unresolved_requirements: list[str] = Field(default_factory=list)
    runtime_provided_requirements: list[str] = Field(default_factory=list)
    blocked_requirements: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list, max_length=12)


class ResourceValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["complete", "needs_input", "blocked", "failed"]
    validated_resources: dict[str, object] = Field(default_factory=dict)
    invalid_resources: dict[str, str] = Field(default_factory=dict)
    validation_evidence: list[dict[str, object]] = Field(default_factory=list)


class ResourceReactDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["continue_checking", "needs_user_input", "resources_ready", "blocked", "failed"]
    requirements: list[ResourceRequirement] = Field(default_factory=list)
    check_results_summary: list[dict[str, object]] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    user_prompt: str = ""
    resource_draft: dict[str, object] = Field(default_factory=dict)
    validation_notes: list[str] = Field(default_factory=list)


class ResourceAndConditionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["collecting", "complete", "blocked", "failed", "needs_input"]
    requirements: list[ResourceRequirement] = Field(default_factory=list)
    check_plans: list[ResourceCheckPlan] = Field(default_factory=list)
    check_results: list[ResourceCheckResult] = Field(default_factory=list)
    readiness_analysis: ResourceReadinessAnalysis | None = None
    user_inputs: list[ResourceUserInput] = Field(default_factory=list)
    resource_draft: dict[str, object] = Field(default_factory=dict)
    validation_result: ResourceValidationResult | None = None
    resources: dict[str, object] = Field(default_factory=dict)
    resource_file_path: str | None = None


class AssemblyDraftPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: AgentSpec
    runtime: RuntimeSpec
    graph_overrides: GraphOverrides = Field(default_factory=GraphOverrides)
    tools: list[ToolSpec] = Field(default_factory=list)
    output: OutputSpec = Field(default_factory=OutputSpec)
    metadata: dict[str, object] = Field(default_factory=dict)


class AssemblyReactDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["draft_ready", "blocked", "failed"]
    draft: AssemblyDraftPayload | None = None
    revision_notes: list[str] = Field(default_factory=list, max_length=12)
    blocked_reason: str = ""


class AssemblyValidationAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt: int
    status: Literal["valid", "invalid"]
    errors: list[str] = Field(default_factory=list)


class AssemblyValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["assembly_validation.v0"] = "assembly_validation.v0"
    status: Literal["valid", "invalid", "failed"]
    attempts: list[AssemblyValidationAttempt] = Field(default_factory=list)
    final_error: str = ""
