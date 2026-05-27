from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from packaging.requirements import InvalidRequirement, Requirement
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_factory.assembly.schema import ToolSpec
from agent_factory.scheduler_system.schema import SchedulerSeedPlan


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
ResourceResolutionStrategy = Literal[
    "ask_user",
    "discoverable",
    "secret",
    "optional",
    "runtime_config",
    "defaultable",
]
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


RESERVED_PACKAGE_STATE_NAMESPACES = {
    "artifact",
    "artifacts",
    "context",
    "knowledge",
    "memory",
    "messages",
    "model_context",
    "resources",
    "runtime",
    "scheduler",
    "tools",
    "trace",
}
_RESOURCE_SELECTOR_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")


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


class RuntimeDesignStateNamespacePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    namespace: str
    purpose: str
    owned_by_nodes: list[str] = Field(default_factory=list)
    initial_shape: dict[str, object] = Field(default_factory=dict)

    @field_validator("namespace")
    @classmethod
    def _namespace_is_business_owned(cls, value: str) -> str:
        namespace = value.strip()
        if not namespace:
            raise ValueError("state namespace must not be empty")
        if namespace in RESERVED_PACKAGE_STATE_NAMESPACES:
            raise ValueError(f"state namespace is reserved for RuntimeKernel services: {namespace}")
        return namespace

    @field_validator("purpose")
    @classmethod
    def _purpose_is_not_empty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("state namespace purpose must not be empty")
        return text


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


class RuntimeDesignPromptSlotBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["prompt"] = "prompt"
    prompt_id: str


class RuntimeDesignToolSlotBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["tool"] = "tool"
    tool_ids: list[str] = Field(default_factory=list)
    generated_tool_ids: list[str] = Field(default_factory=list)


class RuntimeDesignResourceSlotBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["resource"] = "resource"
    resource_id: str
    value_schema: dict[str, Any] = Field(default_factory=dict)
    default_value: dict[str, Any] = Field(default_factory=dict)
    secret_fields: list[str] = Field(default_factory=list)
    resolution_strategy: list[ResourceResolutionStrategy]


class RuntimeDesignStateSlotBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["state"] = "state"
    namespace: str
    path: list[str] = Field(default_factory=list)


class RuntimeDesignSchedulerSlotBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["scheduler"] = "scheduler"
    target_type: Literal["graph_run", "tool_call", "script_run"] = "graph_run"
    schedule_intent: str
    target_message: str = ""


class RuntimeDesignArtifactSlotBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["artifact"] = "artifact"
    artifact_kind: str = "report"
    output_intent: str


class RuntimeDesignStructuredOutputSlotBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["structured_output"] = "structured_output"
    output_id: str


class RuntimeDesignPackageNodeSlotBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["package_node"] = "package_node"
    impl_id: str


class RuntimeDesignCapabilitySlotBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["knowledge", "memory", "context"]
    strategy: str


RuntimeDesignSlotBinding = Annotated[
    RuntimeDesignPromptSlotBinding
    | RuntimeDesignToolSlotBinding
    | RuntimeDesignResourceSlotBinding
    | RuntimeDesignStateSlotBinding
    | RuntimeDesignSchedulerSlotBinding
    | RuntimeDesignArtifactSlotBinding
    | RuntimeDesignStructuredOutputSlotBinding
    | RuntimeDesignPackageNodeSlotBinding
    | RuntimeDesignCapabilitySlotBinding,
    Field(discriminator="kind"),
]


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
    binding: RuntimeDesignSlotBinding

    @field_validator("slot_id", "purpose", "binding_strategy")
    @classmethod
    def _slot_text_is_not_empty(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("slot_id, purpose, and binding_strategy must not be empty")
        return text

    @field_validator("required_by_nodes")
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

    @model_validator(mode="after")
    def _binding_matches_slot_type(self) -> "RuntimeDesignSlotPlan":
        if self.binding.kind != self.slot_type:
            raise ValueError(f"slot binding kind must match slot_type: {self.slot_type}")
        return self


class RuntimeDesignOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["runtime_design.v0"] = "runtime_design.v0"
    design_mode: RuntimeDesignMode = "reuse_pattern"
    selected_pattern_id: str
    graph_intent: str
    nodes: list[RuntimeDesignNodePlan] = Field(default_factory=list)
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
    source: Literal["package_generated", "builtin", "mcp", "skill", "knowledge", "scheduler"] | None = None
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
    value_schema: dict[str, Any] = Field(default_factory=dict)
    default_value: dict[str, Any] = Field(default_factory=dict)
    secret_fields: list[str] = Field(default_factory=list)
    resolution_strategy: list[ResourceResolutionStrategy]
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


class ExternalResourceDiscoveryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    query: str
    target_resource_id: str = ""
    target_path: list[str] = Field(default_factory=list)
    reason: str = ""

    @field_validator("question", "query")
    @classmethod
    def _discovery_text_is_non_empty(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("discovery question and query must not be empty")
        return text


class ExternalResourceDiscoveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: ExternalResourceDiscoveryQuery
    status: Literal["completed", "unavailable", "failed"] = "completed"
    tool_id: str = ""
    summary: str = ""
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    error: str = ""


class ResourceFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    value: Any = None
    secret: bool = False
    status: Literal["confirmed", "discovered", "declined", "missing", "optional_empty"] = "confirmed"
    source: Literal["user", "tool", "knowledge", "mcp", "skill", "default", "system"] = "user"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    required_by: list[str] = Field(default_factory=list)

    @field_validator("key")
    @classmethod
    def _key_is_non_empty(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("resource fact key must not be empty")
        return text


class ResourceResolutionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["resource_resolution_report.v0"] = "resource_resolution_report.v0"
    status: Literal["valid", "needs_input", "skipped", "failed"] = "valid"
    facts_count: int = 0
    missing_questions: list[str] = Field(default_factory=list)
    discovery_results: list[ExternalResourceDiscoveryResult] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ExternalResourceResolutionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["external_resource_resolution.v0"] = "external_resource_resolution.v0"
    decision: Literal["resolved", "needs_clarification", "skip"] = "resolved"
    resources: dict[str, Any] = Field(default_factory=dict)
    sandbox: dict[str, Any] = Field(default_factory=dict)
    discovery_queries: list[ExternalResourceDiscoveryQuery] = Field(default_factory=list, max_length=5)
    discovery_results: list[ExternalResourceDiscoveryResult] = Field(default_factory=list, max_length=5)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    missing_questions: list[str] = Field(default_factory=list, max_length=5)
    notes: list[str] = Field(default_factory=list, max_length=8)


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

    @field_validator("resources")
    @classmethod
    def _resource_selectors_are_valid(cls, value: dict[str, str]) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        for local_name, selector in value.items():
            local = str(local_name).strip()
            target = str(selector).strip()
            if not local or not target:
                raise ValueError("tool resource mappings must not contain empty keys or selectors")
            if "{{" in target or "}}" in target:
                raise ValueError("tool resource mappings must use resource selectors, not template expressions")
            if not _RESOURCE_SELECTOR_PATTERN.fullmatch(target):
                raise ValueError(f"invalid tool resource selector: {target}")
            cleaned[local] = target
        return cleaned


ToolManufacturingSource = Literal["package_generated", "builtin", "mcp", "skill", "knowledge", "scheduler"]


class ToolInheritedExtensionRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["mcp", "skill"]
    extension_id: str
    required: bool = False
    reason: str = ""

    @field_validator("extension_id")
    @classmethod
    def _extension_id_is_non_empty(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("extension_id must not be empty")
        return text


class InheritedExtensionArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["mcp", "skill"]
    extension_id: str
    config: dict[str, Any]
    source_path: str | None = None
    target_path: str | None = None

    @field_validator("extension_id")
    @classmethod
    def _extension_id_is_non_empty(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("extension_id must not be empty")
        return text


class ToolSourceDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str
    source: ToolManufacturingSource
    selected_tool_id: str | None = None
    inherited_extensions: list[ToolInheritedExtensionRef] = Field(default_factory=list)
    rationale: str
    required_by_nodes: list[str] = Field(default_factory=list)
    binding_notes: str = ""

    @field_validator("tool_id")
    @classmethod
    def _tool_id_is_snake_case(cls, value: str) -> str:
        return PackageToolBuildPlan._tool_id_is_snake_case(value)

    @field_validator("rationale")
    @classmethod
    def _rationale_is_non_empty(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("tool source decision rationale must not be empty")
        return text


class ToolResourceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_name: str
    selector: str
    purpose: str = ""

    @field_validator("local_name")
    @classmethod
    def _local_name_is_identifier(cls, value: str) -> str:
        name = str(value).strip()
        if not _RESOURCE_SELECTOR_PATTERN.fullmatch(name):
            raise ValueError("local_name must be an identifier-style local resource name")
        if "." in name:
            raise ValueError("local_name must not contain dots; use selector for resource paths")
        return name

    @field_validator("selector")
    @classmethod
    def _selector_is_dot_path(cls, value: str) -> str:
        selector = str(value).strip()
        if "{{" in selector or "}}" in selector:
            raise ValueError("resource selector must not be a template expression")
        if not _RESOURCE_SELECTOR_PATTERN.fullmatch(selector):
            raise ValueError(f"invalid tool resource selector: {selector}")
        return selector


class ToolDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str
    purpose: str
    input_semantics: str
    output_semantics: str
    failure_semantics: str
    resource_bindings: list[ToolResourceBinding] = Field(
        default_factory=list,
        description="Explicit resource bindings. Each item is local_name -> selector; selector is a dot path such as report_config.news_api_key.",
    )
    risk_level: Literal["low", "medium", "high"] = "medium"
    concurrent: bool = True
    python_requirements: list[str] = Field(default_factory=list)
    system_packages: list[str] = Field(default_factory=list)
    system_binaries: list[str] = Field(default_factory=list)
    implementation_constraints: list[str] = Field(default_factory=list)
    test_resources: dict[str, Any] = Field(default_factory=dict)
    test_arguments: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tool_id")
    @classmethod
    def _tool_id_is_snake_case(cls, value: str) -> str:
        return PackageToolBuildPlan._tool_id_is_snake_case(value)

    @field_validator("purpose", "input_semantics", "output_semantics", "failure_semantics")
    @classmethod
    def _text_is_non_empty(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("tool design text fields must not be empty")
        return text

    @field_validator("python_requirements")
    @classmethod
    def _python_requirements_are_valid(cls, value: list[str]) -> list[str]:
        return _validate_python_requirements(value)

    @field_validator("system_packages", "system_binaries")
    @classmethod
    def _system_dependencies_are_valid(cls, value: list[str]) -> list[str]:
        return _validate_dependency_names(value)


class ToolSpecDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    resources: dict[str, str] = Field(default_factory=dict)
    risk_level: Literal["low", "medium", "high"] = "medium"
    concurrent: bool = True

    @field_validator("tool_id")
    @classmethod
    def _tool_id_is_snake_case(cls, value: str) -> str:
        return PackageToolBuildPlan._tool_id_is_snake_case(value)

    @field_validator("description")
    @classmethod
    def _description_is_non_empty(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("tool spec description must not be empty")
        return text

    @field_validator("input_schema", "output_schema")
    @classmethod
    def _schema_is_object(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict) or not value:
            raise ValueError("tool schemas must be non-empty JSON objects")
        return value

    @field_validator("resources")
    @classmethod
    def _resource_selectors_are_valid(cls, value: dict[str, str]) -> dict[str, str]:
        return PackageToolBuildPlan._resource_selectors_are_valid(value)


class ToolImplementationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str
    code: str
    notes: list[str] = Field(default_factory=list)

    @field_validator("tool_id")
    @classmethod
    def _tool_id_is_snake_case(cls, value: str) -> str:
        return PackageToolBuildPlan._tool_id_is_snake_case(value)

    @field_validator("code")
    @classmethod
    def _code_is_non_empty(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("tool implementation code must not be empty")
        return text


class ToolTrialScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    user_prompt: str
    expected_tool_id: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    resources: dict[str, Any] = Field(default_factory=dict)
    expected_observation_status: Literal[
        "completed",
        "invalid_arguments",
        "invalid_output",
        "execution_failed",
        "denied",
        "revision_requested",
    ] = "completed"
    expected_output_keys: list[str] = Field(default_factory=list)
    expected_final_answer_contains: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)

    @field_validator("expected_tool_id")
    @classmethod
    def _tool_id_is_snake_case(cls, value: str) -> str:
        return PackageToolBuildPlan._tool_id_is_snake_case(value)

    @field_validator("scenario_id", "user_prompt")
    @classmethod
    def _scenario_text_is_non_empty(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("scenario_id and user_prompt must not be empty")
        return text


class ToolTrialPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str
    scenarios: list[ToolTrialScenario] = Field(default_factory=list, min_length=1)
    expected_coverage: list[str] = Field(default_factory=list)

    @field_validator("tool_id")
    @classmethod
    def _tool_id_is_snake_case(cls, value: str) -> str:
        return PackageToolBuildPlan._tool_id_is_snake_case(value)

    @model_validator(mode="after")
    def _scenarios_target_this_tool(self) -> "ToolTrialPlan":
        for scenario in self.scenarios:
            if scenario.expected_tool_id != self.tool_id:
                raise ValueError("each trial scenario expected_tool_id must match ToolTrialPlan.tool_id")
        return self


class ToolManufacturingFailureSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str
    phase: Literal[
        "required_artifacts",
        "artifact_ids",
        "python_compile",
        "entrypoint_signature",
        "tool_spec",
        "dependency_convergence",
        "contract_smoke",
        "resource_probe",
        "model_trial",
        "manufacturing_alignment",
    ]
    category: str
    primary_error: str
    report_path: str = ""
    suggested_action: str = ""


class ToolManufacturingCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["passed", "failed", "skipped"]
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    failure_summary: ToolManufacturingFailureSummary | None = None


class ToolManufacturingReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["tool_manufacturing_report.v0"] = "tool_manufacturing_report.v0"
    status: Literal["valid", "invalid", "failed"]
    source_decisions: list[ToolSourceDecision] = Field(default_factory=list)
    checks: list[ToolManufacturingCheck] = Field(default_factory=list)
    approved_tool_ids: list[str] = Field(default_factory=list)
    blocked_tool_ids: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ApprovedPackageToolArtifact(PackageToolBuildPlan):
    model_config = ConfigDict(extra="forbid")

    manufacturing_status: Literal["approved"] = "approved"
    manufacturing_report_ref: str = ""


class ToolManufacturingOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["tool_manufacturing.v0"] = "tool_manufacturing.v0"
    source_decisions: list[ToolSourceDecision] = Field(default_factory=list)
    tool_designs: list[ToolDesign] = Field(default_factory=list)
    tool_specs: list[ToolSpecDraft] = Field(default_factory=list)
    implementations: list[ToolImplementationDraft] = Field(default_factory=list)
    trial_plans: list[ToolTrialPlan] = Field(default_factory=list)
    approved_package_tools: list[ApprovedPackageToolArtifact] = Field(default_factory=list)
    inherited_extensions: list[InheritedExtensionArtifact] = Field(default_factory=list)
    report: ToolManufacturingReport = Field(default_factory=lambda: ToolManufacturingReport(status="valid"))
    manufacturing_summary_text: str = ""


class SchedulerSeedValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["valid", "invalid"]
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SchedulerPreparationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["scheduler_preparation.v0"] = "scheduler_preparation.v0"
    approved_seeds: list[SchedulerSeedPlan] = Field(default_factory=list)
    display_summary: str = ""
    warnings: list[str] = Field(default_factory=list, max_length=10)
    validation_report: SchedulerSeedValidationReport = Field(
        default_factory=lambda: SchedulerSeedValidationReport(status="valid")
    )

    @field_validator("approved_seeds")
    @classmethod
    def _seed_ids_are_unique(cls, values: list[SchedulerSeedPlan]) -> list[SchedulerSeedPlan]:
        seen: set[str] = set()
        for item in values:
            if item.seed_id in seen:
                raise ValueError(f"duplicate scheduler seed_id: {item.seed_id}")
            seen.add(item.seed_id)
        return values


class SchedulerSeedRevisionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "revise", "skip"]
    seeds: list[SchedulerSeedPlan] = Field(default_factory=list)
    display_summary: str = ""
    warnings: list[str] = Field(default_factory=list, max_length=10)


class ToolSourceDecisionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["tool_source_decisions.v0"] = "tool_source_decisions.v0"
    source_decisions: list[ToolSourceDecision] = Field(default_factory=list)
    manufacturing_summary_text: str = ""


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


class PackageBuildModelPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["package_build_plan.v0"] = "package_build_plan.v0"
    package_id: str
    agent_id: str
    agent_name: str
    agent_description: str
    prompt_templates: list[PackagePromptBuildPlan] = Field(default_factory=list)
    structured_outputs: list[PackageStructuredOutputBuildPlan] = Field(default_factory=list)
    package_nodes: list[PackageNodeBuildPlan] = Field(default_factory=list)
    build_summary_text: str = ""
    warnings: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("package_id", "agent_id")
    @classmethod
    def _ids_are_package_safe(cls, value: str) -> str:
        return PackageBuildPlan._ids_are_package_safe(value)

    @field_validator("agent_name", "agent_description")
    @classmethod
    def _agent_text_is_not_empty(cls, value: str) -> str:
        return PackageBuildPlan._agent_text_is_not_empty(value)

    def to_package_build_plan(self, *, package_tools: list[PackageToolBuildPlan]) -> PackageBuildPlan:
        return PackageBuildPlan.model_validate(
            {
                **self.model_dump(mode="json"),
                "package_tools": [item.model_dump(mode="json") for item in package_tools],
            }
        )


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
    scheduler_seed_count: int = Field(default=0, ge=0)
