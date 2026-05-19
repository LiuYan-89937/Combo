from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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
    image: str = "python:3.12-slim"
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
SandboxInstallMode = Literal["none", "sandbox_only"]
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
    image: str = "python:3.11-slim"
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
