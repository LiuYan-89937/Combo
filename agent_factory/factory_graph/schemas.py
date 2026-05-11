from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
