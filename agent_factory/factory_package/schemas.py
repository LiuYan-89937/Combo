from __future__ import annotations

from typing import Any, Literal

from packaging.requirements import InvalidRequirement, Requirement
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_factory.assembly.schema import (
    AgentSpec,
    GraphOverrides,
    OutputSpec,
    RuntimeSpec,
    ToolSpec,
)
from agent_factory.runtime_kernel.bindings import BindingSet


class CaptureIntentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal["chat", "inspect_factory", "manufacture_agent", "repair_agent", "unclear"]
    confidence: float = Field(ge=0, le=1)
    reason: str
    extracted_requirement: str | None = None
    reply_hint: str | None = None
    entry_stage: str | None = None
    should_run_graph: bool


class ProductBriefOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["product_brief.v0"] = "product_brief.v0"
    working_title: str = ""
    agent_goal: str = ""
    target_user: str = ""
    first_version_scope: str = ""
    primary_workflow: str = ""
    autonomy_boundary: str = ""
    human_review_boundary: str = ""
    resource_boundary: str = ""
    expected_outputs: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    manufacturing_assumptions: list[str] = Field(default_factory=list)
    blocking_questions: list[str] = Field(default_factory=list, max_length=2)
    business_plan_text: str = ""
    ready_for_runtime_design: bool = False


RuntimeDesignMode = Literal["reuse_pattern"]
RuntimeDesignModelOperation = Literal["none", "text", "tool_bound_chat", "structured_json"]
RuntimeDesignNodeType = Literal["reserved", "cognitive", "operational", "governance", "terminal", "sub_graph"]
RuntimeDesignSlotType = Literal[
    "prompt",
    "tool",
    "resource",
    "state",
    "scheduler",
    "structured_output",
    "package_node",
    "artifact",
    "knowledge",
    "memory",
    "context",
]


class RuntimeDesignNodePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    node_type: RuntimeDesignNodeType
    impl: str
    purpose: str
    model_operation: RuntimeDesignModelOperation = "none"
    pattern_ref: str | None = None
    requires_tools: bool = False
    tool_access_required: list[str] = Field(default_factory=list)
    requires_structured_output: bool = False
    structured_output_id: str | None = None
    requires_package_node: bool = False
    package_node_impl_id: str | None = None
    reads_state: list[str] = Field(default_factory=list)
    writes_state: list[str] = Field(default_factory=list)
    visible_to_user: bool = True
    notes: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("node_id")
    @classmethod
    def _node_id_is_simple(cls, value: str) -> str:
        node_id = value.strip()
        if not node_id:
            raise ValueError("node_id must not be empty")
        return node_id

    @model_validator(mode="after")
    def _package_node_shape(self) -> "RuntimeDesignNodePlan":
        if self.requires_package_node:
            if not self.package_node_impl_id:
                raise ValueError("requires_package_node=true requires package_node_impl_id")
            if not self.package_node_impl_id.startswith("package."):
                raise ValueError("package_node_impl_id must start with package.")
        if self.node_type == "sub_graph" and not self.pattern_ref:
            raise ValueError("sub_graph nodes require pattern_ref")
        if self.node_type != "sub_graph" and self.pattern_ref:
            raise ValueError("pattern_ref is only valid for sub_graph nodes")
        if self.requires_structured_output and self.model_operation != "structured_json":
            raise ValueError("requires_structured_output requires model_operation=structured_json")
        return self


class RuntimeDesignEdgePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_node: str
    to_node: str
    when: str
    business_meaning: str = ""


class RuntimeDesignInterruptPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    reason: str
    user_visible_reason: str


class RuntimeDesignTerminationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success_nodes: list[str] = Field(default_factory=list)
    failure_nodes: list[str] = Field(default_factory=list)
    success_meaning: str = ""
    failure_meaning: str = ""


class RuntimeDesignStateNamespacePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    namespace: str
    purpose: str
    owned_by_nodes: list[str] = Field(default_factory=list)
    initial_shape: dict[str, object] = Field(default_factory=dict)


class RuntimeDesignStructuredOutputPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_id: str
    produced_by_node: str
    purpose: str
    write_target: dict[str, object] = Field(default_factory=dict)
    schema_summary: str


class RuntimeDesignPackageNodePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    impl_id: str
    node_id: str
    purpose: str
    why_standard_nodes_are_not_enough: str
    required_services: list[str] = Field(default_factory=list)
    tool_access: list[str] = Field(default_factory=list)

    @field_validator("impl_id")
    @classmethod
    def _impl_id_is_package_scoped(cls, value: str) -> str:
        impl_id = value.strip()
        if not impl_id.startswith("package."):
            raise ValueError("package node impl_id must start with package.")
        return impl_id


class RuntimeDesignSlotPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_id: str
    slot_type: RuntimeDesignSlotType
    required_by_nodes: list[str] = Field(default_factory=list)
    purpose: str
    source: Literal[
        "builtin",
        "package_generated",
        "system",
        "runtime_config",
        "user_config",
        "mcp",
        "skill",
        "knowledge",
        "scheduler",
        "artifact",
        "none",
    ] = "system"
    binding_strategy: str
    state_path: list[str] = Field(default_factory=list)
    tool_id: str | None = None
    resource_id: str | None = None
    prompt_id: str | None = None

    @field_validator("slot_id", "purpose", "binding_strategy")
    @classmethod
    def _slot_text_is_not_empty(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("slot_id, purpose, and binding_strategy must not be empty")
        return text

    @field_validator("required_by_nodes", "state_path")
    @classmethod
    def _string_list_is_clean(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw in value:
            item = str(raw).strip()
            if not item:
                raise ValueError("slot list fields must not contain empty values")
            if item not in seen:
                result.append(item)
                seen.add(item)
        return result


class RuntimeDesignOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["runtime_design.v0"] = "runtime_design.v0"
    design_mode: RuntimeDesignMode = "reuse_pattern"
    selected_pattern_id: str
    graph_intent: str
    nodes: list[RuntimeDesignNodePlan] = Field(default_factory=list)
    edges: list[RuntimeDesignEdgePlan] = Field(default_factory=list)
    interrupts: list[RuntimeDesignInterruptPlan] = Field(default_factory=list)
    termination: RuntimeDesignTerminationPlan = Field(default_factory=RuntimeDesignTerminationPlan)
    state_namespaces: list[RuntimeDesignStateNamespacePlan] = Field(default_factory=list)
    required_contracts: list[str] = Field(default_factory=list)
    pattern_slots: list[RuntimeDesignSlotPlan] = Field(default_factory=list)
    package_nodes_to_generate: list[RuntimeDesignPackageNodePlan] = Field(default_factory=list)
    structured_outputs: list[RuntimeDesignStructuredOutputPlan] = Field(default_factory=list)
    runtime_assumptions: list[str] = Field(default_factory=list, max_length=10)
    blocking_questions: list[str] = Field(default_factory=list, max_length=2)
    design_summary_text: str = ""

    @model_validator(mode="after")
    def _mode_shape(self) -> "RuntimeDesignOutput":
        if not self.selected_pattern_id.strip():
            raise ValueError("reuse_pattern requires selected_pattern_id")
        if self.edges:
            raise ValueError("Runtime Design must not emit custom edges; choose a preset pattern instead")
        if self.termination.success_nodes or self.termination.failure_nodes:
            raise ValueError("Runtime Design must not emit custom termination; preset pattern owns termination")
        return self


class RuntimeDesignValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["valid", "invalid"]
    design_mode: RuntimeDesignMode
    selected_pattern_id: str | None = None
    candidate_pattern_id: str | None = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    validated_pattern_summary: dict[str, object] = Field(default_factory=dict)


class CapabilityPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    why: str
    what: dict[str, Any] = Field(default_factory=dict)
    strategy: dict[str, Any] = Field(default_factory=dict)
    risks: list[str] = Field(default_factory=list)
    deferred_decisions: list[str] = Field(default_factory=list)


class CapabilityContractDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    version: str
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class CapabilityToolGenerationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str
    purpose: str
    source: Literal["package_generated", "builtin", "mcp", "skill", "knowledge", "scheduler"]
    required_by_nodes: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "medium"
    input_summary: str = ""
    output_summary: str = ""


class CapabilityPackageNodeGenerationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    impl_id: str
    node_id: str
    purpose: str
    required_services: list[str] = Field(default_factory=list)
    tool_access: list[str] = Field(default_factory=list)
    state_reads: list[str] = Field(default_factory=list)
    state_writes: list[str] = Field(default_factory=list)

    @field_validator("impl_id")
    @classmethod
    def _impl_id_is_package_scoped(cls, value: str) -> str:
        impl_id = value.strip()
        if not impl_id.startswith("package."):
            raise ValueError("package node impl_id must start with package.")
        return impl_id


class CapabilityPromptGenerationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_id: str
    used_by_node: str
    purpose: str
    output_mode: Literal["text", "structured_json", "tool_bound_chat"] = "text"


class CapabilityBindingGenerationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    binding_id: str
    node_id: str
    binding_type: str
    purpose: str
    payload_summary: str = ""


class CapabilityResourceRequirementPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str
    description: str
    required: bool = True
    expected_shape: str = ""
    sandbox_access_expectation: str = ""
    used_by: list[str] = Field(default_factory=list)


class CapabilitySandboxRequirementPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: str
    description: str
    network_required: bool = False
    mounts_required: list[str] = Field(default_factory=list)
    secrets_required: list[str] = Field(default_factory=list)
    services_required: list[str] = Field(default_factory=list)


class CapabilityContractOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["capability_contract.v0"] = "capability_contract.v0"
    contract_drafts: dict[str, CapabilityContractDraft] = Field(default_factory=dict)
    capability_plans: dict[str, CapabilityPlan] = Field(default_factory=dict)
    tool_specs_to_generate: list[CapabilityToolGenerationPlan] = Field(default_factory=list)
    package_nodes_to_generate: list[CapabilityPackageNodeGenerationPlan] = Field(default_factory=list)
    prompts_to_generate: list[CapabilityPromptGenerationPlan] = Field(default_factory=list)
    bindings_to_generate: list[CapabilityBindingGenerationPlan] = Field(default_factory=list)
    resources_required: list[CapabilityResourceRequirementPlan] = Field(default_factory=list)
    sandbox_requirements: list[CapabilitySandboxRequirementPlan] = Field(default_factory=list)
    capability_summary_text: str = ""
    risks: list[str] = Field(default_factory=list, max_length=10)
    deferred_decisions: list[str] = Field(default_factory=list, max_length=10)


class CapabilityContractValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["valid", "invalid"]
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    enabled_contracts: list[str] = Field(default_factory=list)
    disabled_contracts: list[str] = Field(default_factory=list)
    generation_task_summary: dict[str, int] = Field(default_factory=dict)


class PackagePromptBuildPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_id: str
    node_id: str
    template: str
    variables: list[str] = Field(default_factory=list)

    @field_validator("prompt_id", "node_id", "template")
    @classmethod
    def _non_empty_string(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("prompt build fields must not be empty")
        return text


class PackageStructuredOutputBuildPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_id: str
    node_id: str
    output_schema: dict[str, Any]
    write_target: dict[str, Any]
    prompt_id: str | None = None
    max_attempts: int = Field(default=5, ge=1)
    structured_method: str | None = "json_mode"

    @field_validator("output_id", "node_id")
    @classmethod
    def _ids_are_non_empty(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("structured output fields must not be empty")
        return text

    @field_validator("output_schema", "write_target")
    @classmethod
    def _objects_are_non_empty(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict) or not value:
            raise ValueError("structured output schema and write_target must be non-empty objects")
        return value


class PackageNodeBuildPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    impl_id: str
    node_id: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "additionalProperties": True})
    output_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "additionalProperties": True})
    readable_sections: list[str] = Field(default_factory=list)
    writable_sections: list[str] = Field(default_factory=list)
    required_services: list[str] = Field(default_factory=list)
    tool_access: list[str] = Field(default_factory=list)
    python_requirements: list[str] = Field(default_factory=list)
    system_packages: list[str] = Field(default_factory=list)
    system_binaries: list[str] = Field(default_factory=list)
    code: str

    @field_validator("impl_id")
    @classmethod
    def _impl_id_is_package_scoped(cls, value: str) -> str:
        impl_id = value.strip()
        if not impl_id.startswith("package."):
            raise ValueError("package node impl_id must start with package.")
        return impl_id

    @field_validator("node_id", "description", "code")
    @classmethod
    def _node_fields_are_non_empty(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("package node build fields must not be empty")
        return text

    @field_validator("python_requirements")
    @classmethod
    def _python_requirements_are_valid(cls, value: list[str]) -> list[str]:
        return _validate_python_requirements(value)

    @field_validator("system_packages", "system_binaries")
    @classmethod
    def _system_dependencies_are_valid(cls, value: list[str]) -> list[str]:
        return _validate_dependency_names(value)


class PackageToolBuildPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "additionalProperties": True})
    output_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "additionalProperties": True})
    resources: dict[str, str] = Field(default_factory=dict)
    risk_level: Literal["low", "medium", "high"] = "medium"
    concurrent: bool = True
    python_requirements: list[str] = Field(default_factory=list)
    system_packages: list[str] = Field(default_factory=list)
    system_binaries: list[str] = Field(default_factory=list)
    code: str

    @field_validator("tool_id")
    @classmethod
    def _tool_id_is_snake_case(cls, value: str) -> str:
        tool_id = str(value).strip()
        if not tool_id or not tool_id.replace("_", "").isalnum() or tool_id[0].isdigit() or tool_id.lower() != tool_id:
            raise ValueError("tool_id must be lowercase snake_case")
        return tool_id

    @field_validator("description", "code")
    @classmethod
    def _tool_fields_are_non_empty(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("package tool build fields must not be empty")
        return text

    @field_validator("python_requirements")
    @classmethod
    def _python_requirements_are_valid(cls, value: list[str]) -> list[str]:
        return _validate_python_requirements(value)

    @field_validator("system_packages", "system_binaries")
    @classmethod
    def _system_dependencies_are_valid(cls, value: list[str]) -> list[str]:
        return _validate_dependency_names(value)


def _validate_python_requirements(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        requirement = str(raw).strip()
        if not requirement:
            raise ValueError("python requirements must not contain empty values")
        try:
            Requirement(requirement)
        except InvalidRequirement as exc:
            raise ValueError(f"invalid Python requirement: {requirement}") from exc
        if requirement not in seen:
            result.append(requirement)
            seen.add(requirement)
    return result


def _validate_dependency_names(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw).strip()
        if not value:
            raise ValueError("dependency names must not contain empty values")
        if any(character.isspace() for character in value):
            raise ValueError(f"dependency names must not contain whitespace: {value}")
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


class PackageBuildPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["package_build_plan.v0"] = "package_build_plan.v0"
    package_id: str
    agent_id: str
    agent_name: str
    agent_description: str
    prompt_templates: list[PackagePromptBuildPlan] = Field(default_factory=list)
    structured_outputs: list[PackageStructuredOutputBuildPlan] = Field(default_factory=list)
    package_nodes: list[PackageNodeBuildPlan] = Field(default_factory=list)
    package_tools: list[PackageToolBuildPlan] = Field(default_factory=list)
    build_summary_text: str = ""
    warnings: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("package_id", "agent_id")
    @classmethod
    def _ids_are_package_safe(cls, value: str) -> str:
        item = str(value).strip()
        if not item:
            raise ValueError("package_id and agent_id must not be empty")
        if any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for ch in item):
            raise ValueError("package_id and agent_id must use lowercase letters, numbers, underscore, or dash")
        if item[0].isdigit():
            item = f"agent_{item}"
        return item

    @field_validator("agent_name", "agent_description")
    @classmethod
    def _agent_text_is_not_empty(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("agent_name and agent_description must not be empty")
        return text


class PackageBuildMaterializedFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    file_type: Literal["json", "yaml", "markdown", "python", "text"]
    generation_mode: Literal["system_generated", "model_generated"]
    source: str
    bytes: int
    sha256: str


class PackageBuildStaticCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["passed", "failed"]
    message: str = ""


class PackageBuildReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["package_build_report.v0"] = "package_build_report.v0"
    status: Literal["valid", "invalid", "failed"]
    package_root: str
    manifest_path: str = ""
    materialized_files: list[PackageBuildMaterializedFile] = Field(default_factory=list)
    static_checks: list[PackageBuildStaticCheck] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RequirementClarityOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_clear: bool
    confidence: float = Field(ge=0, le=1)
    reason: str
    missing_fields: list[str] = Field(default_factory=list, max_length=5)


class RequirementFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = ""
    primary_users: list[str] = Field(default_factory=list, max_length=5)
    primary_scenarios: list[str] = Field(default_factory=list, max_length=5)
    behavior_mode: str = ""
    action_boundary: str = ""
    resource_scope: list[str] = Field(default_factory=list, max_length=8)
    output_expectation: str = ""
    success_signal: str = ""
    out_of_scope: list[str] = Field(default_factory=list, max_length=8)
    human_approval_expectations: list[str] = Field(default_factory=list, max_length=5)
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    unknowns: list[str] = Field(default_factory=list, max_length=8)


class ClarificationOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    description: str | None = None


class ClarifyingQuestionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    question: str
    options: list[ClarificationOption] = Field(min_length=2, max_length=4)
    custom_option_id: str


class ClarifyingQuestionSetOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[ClarifyingQuestionOutput] = Field(min_length=1, max_length=2)


class RequirementMergeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_requirement: str
    requirement_frame: RequirementFrame


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


class ResourceRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: str
    description: str
    required: bool = True
    used_by_capability_ids: list[str] = Field(default_factory=list)
    expected_resource_shape: dict[str, Any] = Field(default_factory=dict)
    why_needed: str
    sandbox_access_expectation: str


class SandboxContractMount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str
    host_path: str
    container_path: str
    access: Literal["read_only", "read_write"]
    purpose: str
    authorization_source: Literal["user_authorized", "tool_evidence", "system_required"] = "user_authorized"


class SandboxContractService(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_id: str
    kind: Literal["host_port", "docker_service", "remote_service"]
    endpoint: str
    ports: list[int] = Field(default_factory=list, max_length=16)
    purpose: str


class SandboxContractSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret_id: str
    target_env: str | None = None
    source: Literal["runtime_provided", "user_provided"] = "runtime_provided"
    purpose: str


SandboxNetworkMode = Literal["none", "default_allow", "declared_services"]


class SandboxNetworkPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: SandboxNetworkMode = "default_allow"
    allowed_hosts: list[str] = Field(default_factory=list, max_length=32)


class SandboxContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["sandbox_contract.v0"] = "sandbox_contract.v0"
    backend: Literal["docker"] = "docker"
    image: str = "agentfactory-runtime-python:3.12"
    workdir: str = "/workdir"
    network_policy: SandboxNetworkPolicy = Field(default_factory=SandboxNetworkPolicy)
    mounts: list[SandboxContractMount] = Field(default_factory=list)
    services: list[SandboxContractService] = Field(default_factory=list)
    secrets: list[SandboxContractSecret] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    volumes: list[SandboxContractMount] = Field(default_factory=list)


class ResourcePreparationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["continue_checking", "needs_user_input", "ready_for_validation", "blocked", "failed"]
    requirements: list[ResourceRequirement] = Field(default_factory=list)
    resource_draft: dict[str, Any] = Field(default_factory=dict)
    sandbox_contract_draft: SandboxContract = Field(default_factory=SandboxContract)
    missing_requirements: list[str] = Field(default_factory=list, max_length=16)
    user_prompt: str = ""
    check_summary: list[str] = Field(default_factory=list, max_length=20)


class ResourcePreparationValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["complete", "needs_input", "blocked", "failed"]
    validated_resources: dict[str, Any] = Field(default_factory=dict)
    validated_sandbox_contract: SandboxContract | None = None
    errors: list[str] = Field(default_factory=list)
    repair_hints: list[str] = Field(default_factory=list, max_length=16)


class AssemblyDraftPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: AgentSpec
    runtime: RuntimeSpec
    graph_overrides: GraphOverrides = Field(default_factory=GraphOverrides)
    bindings: BindingSet
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


PackageFileType = Literal["json", "markdown", "python", "text"]
PackageFileSourceKind = Literal[
    "assembly",
    "binding",
    "prompt",
    "tool",
    "policy",
    "retrieval",
    "strategy",
    "formatter",
    "manifest",
    "contract",
]


class PackageFileDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    content: str
    file_type: PackageFileType
    purpose: str
    source_kind: PackageFileSourceKind
    source_id: str | None = None


PackageGenerationMode = Literal["system_generated", "model_generated"]


class PackageMaterializationFileSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    file_type: PackageFileType
    source_kind: PackageFileSourceKind
    source_id: str | None = None
    generation_mode: PackageGenerationMode
    contract_source: str
    required: bool = True


class PackageMaterializationToolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str
    manifest_path: str
    code_path: str
    readme_path: str
    manifest: ToolSpec


class PackageMaterializationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["package_materialization.v0"] = "package_materialization.v0"
    factory_run_id: str
    package_root: str
    files: list[PackageMaterializationFileSpec] = Field(default_factory=list)
    tools: list[PackageMaterializationToolSpec] = Field(default_factory=list)
    manifest_contract: dict[str, object] = Field(default_factory=dict)
    contracts: dict[str, dict[str, object]] = Field(default_factory=dict)


class PackageMaterializationValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["package_materialization_validation.v0"] = "package_materialization_validation.v0"
    status: Literal["valid", "invalid", "failed"]
    errors: list[str] = Field(default_factory=list)


class PackageBuildDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["package_ready", "blocked", "failed"]
    generated_files: list[PackageFileDraft] = Field(default_factory=list)
    revision_notes: list[str] = Field(default_factory=list, max_length=12)
    blocked_reason: str = ""


class PackageMaterializedFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    file_type: PackageFileType
    source_kind: PackageFileSourceKind
    source_id: str | None = None
    bytes: int


class PackageValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["package_report.v0"] = "package_report.v0"
    status: Literal["valid", "invalid", "failed"]
    package_root: str = ""
    materialized_files: list[PackageMaterializedFile] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    static_checks: list[dict[str, object]] = Field(default_factory=list)


class PackageGenerationState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["collecting", "complete", "blocked", "failed"]
    package_root: str
    manifest_path: str | None = None
    report_path: str | None = None
    materialized_files: list[PackageMaterializedFile] = Field(default_factory=list)
    validation_report: PackageValidationReport | None = None


SandboxBackend = Literal["docker", "local_isolated", "local_trusted"]
SandboxMountAccess = Literal["read_only", "read_write"]
SandboxServiceKind = Literal["host_port", "docker_service", "remote_service"]
SandboxInstallMode = Literal["none", "sandbox_only", "sandbox_init"]
HarnessStatus = Literal["passed", "failed", "blocked"]


class SandboxRuntimeLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeout_seconds: int = Field(default=300, ge=1, le=3600)
    memory_mb: int = Field(default=1024, ge=128, le=32768)
    cpu: float = Field(default=1, gt=0, le=16)


class SandboxEnvPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: list[str] = Field(default_factory=list, max_length=32)
    injected: dict[str, str] = Field(default_factory=dict)


class SandboxDependencyPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    install_mode: SandboxInstallMode = "sandbox_only"
    allow_runtime_install: bool = False


class RuntimeEnvironmentContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: SandboxBackend = "docker"
    image: str = "agentfactory-runtime-python:3.12"
    workdir: str = "/workdir"
    network_policy: SandboxNetworkPolicy = Field(default_factory=SandboxNetworkPolicy)
    limits: SandboxRuntimeLimits = Field(default_factory=SandboxRuntimeLimits)
    env_policy: SandboxEnvPolicy = Field(default_factory=SandboxEnvPolicy)
    dependency_policy: SandboxDependencyPolicy = Field(default_factory=SandboxDependencyPolicy)


class SandboxMount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str
    host_path: str
    container_path: str
    access: SandboxMountAccess
    purpose: str
    authorization_source: Literal["system_required", "resources", "user_authorized"] = "resources"


class SandboxServiceDependency(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_id: str
    kind: SandboxServiceKind
    endpoint: str
    ports: list[int] = Field(default_factory=list, max_length=16)
    health_check: dict[str, Any] = Field(default_factory=dict)


class SandboxSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret_id: str
    source: Literal["runtime_secret", "resources"]
    target_env: str | None = None
    purpose: str


class HostToolProxyContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proxy_id: str
    capability: str
    approval_required: bool = True
    purpose: str


class HostInteractionContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mounts: list[SandboxMount] = Field(default_factory=list)
    volumes: list[SandboxMount] = Field(default_factory=list)
    services: list[SandboxServiceDependency] = Field(default_factory=list)
    secrets: list[SandboxSecret] = Field(default_factory=list)
    host_tool_proxies: list[HostToolProxyContract] = Field(default_factory=list)


class SandboxDependencyPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    python_requirements: list[str] = Field(default_factory=list, max_length=128)
    system_packages: list[str] = Field(default_factory=list, max_length=64)
    install_mode: SandboxInstallMode = "sandbox_only"


class HarnessScenarioPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    input_text: str = ""
    assertions: list[dict[str, Any]] = Field(default_factory=list)


class HarnessToolTestPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    expected_status: str | None = None


class HarnessExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenarios: list[HarnessScenarioPlan] = Field(default_factory=list)
    tool_tests: list[HarnessToolTestPlan] = Field(default_factory=list)
    runtime_assertions: list[dict[str, Any]] = Field(default_factory=list)
    timeout_policy: SandboxRuntimeLimits = Field(default_factory=SandboxRuntimeLimits)


class HarnessContractDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["contracts_ready", "blocked", "failed"]
    runtime_environment: RuntimeEnvironmentContract | None = None
    host_interaction: HostInteractionContract | None = None
    dependency_plan: SandboxDependencyPlan | None = None
    execution_plan: HarnessExecutionPlan | None = None
    revision_notes: list[str] = Field(default_factory=list, max_length=12)
    blocked_reason: str = ""


class HarnessReportError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    where: str
    why: str
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class ArtifactManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    bytes: int
    artifact_type: str = "file"


class HarnessValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["harness_report.v0"] = "harness_report.v0"
    status: HarnessStatus
    factory_run_id: str = ""
    package_root: str = ""
    sandbox_backend: SandboxBackend = "docker"
    contract_validation: dict[str, Any] = Field(default_factory=dict)
    dependency_results: list[dict[str, Any]] = Field(default_factory=list)
    scenario_results: list[dict[str, Any]] = Field(default_factory=list)
    tool_test_results: list[dict[str, Any]] = Field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    artifact_manifest: list[ArtifactManifestEntry] = Field(default_factory=list)
    errors: list[HarnessReportError] = Field(default_factory=list)
    repair_hints: list[str] = Field(default_factory=list, max_length=16)
