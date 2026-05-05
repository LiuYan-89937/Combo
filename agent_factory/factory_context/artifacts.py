from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ConditionRequiredLevel = Literal["blocking", "deferred", "warning"]
ConditionOwner = Literal["factory", "user", "runtime", "agent"]
ConditionStatus = Literal["unknown", "satisfied", "missing", "failed", "deferred"]
ResourceFamily = Literal[
    "data",
    "service",
    "runtime",
    "human",
    "permission",
    "credential",
    "storage",
    "browser",
    "mcp",
    "system",
    "custom",
]
ResourceVisibility = Literal["factory_only", "tool_only", "model_visible", "hidden"]
ReadinessStatus = Literal["ready", "needs_user_input", "blocked", "ready_with_deferred"]


class RequirementUnderstanding(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    agent_name: str | None = None
    agent_type: str | None = None
    goal: str = ""
    audience: str | None = None
    safety_profile: str = "general"
    explicit_requirements: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    source: str = "unknown"


class CapabilityItem(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    capability_id: str
    description: str
    output_expectation: str | None = None
    likely_requires_tools: bool = False
    risk_notes: list[str] = Field(default_factory=list)


class CapabilityPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    capabilities: list[CapabilityItem] = Field(default_factory=list)
    source: str = "factory"


class ConditionItem(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    condition_id: str
    description: str
    required_level: ConditionRequiredLevel = "blocking"
    owner: ConditionOwner = "factory"
    status: ConditionStatus = "unknown"
    evidence_required: list[str] = Field(default_factory=list)
    probe_strategy: str = "none"
    resolution_strategy: str = "none"
    related_resource_ids: list[str] = Field(default_factory=list)
    source_condition_type: str | None = None


class ConditionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    conditions: list[ConditionItem] = Field(default_factory=list)
    source: str = "factory"

    @property
    def blocking_missing(self) -> list[ConditionItem]:
        return [
            condition
            for condition in self.conditions
            if condition.required_level == "blocking"
            and condition.status in {"unknown", "missing", "failed"}
        ]


class ResourceNeed(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    resource_id: str
    family: ResourceFamily = "custom"
    kind: str = "unknown"
    location: str | None = None
    access_mode: Literal["read_only", "read_write"] = "read_only"
    visibility: ResourceVisibility = "tool_only"
    lifecycle: str = "runtime"
    risk_level: str = "medium"
    required_evidence: list[str] = Field(default_factory=list)
    configuration_keys: list[str] = Field(default_factory=list)
    related_condition_ids: list[str] = Field(default_factory=list)


class ResourceNeedPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    resources: list[ResourceNeed] = Field(default_factory=list)
    source: str = "factory"


class EvidenceReport(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    evidence_id: str
    resource_id: str | None = None
    condition_ids: list[str] = Field(default_factory=list)
    source: str
    status: Literal["passed", "failed", "skipped", "partial"] = "skipped"
    summary: str = ""
    artifact_refs: list[str] = Field(default_factory=list)
    safe_for_prompt: bool = True
    details: dict[str, Any] = Field(default_factory=dict)


class ReadinessItem(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    condition_id: str | None = None
    resource_id: str | None = None
    level: ConditionRequiredLevel
    message: str
    resolution_hint: str | None = None


class ResolutionQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    question_id: str
    prompt: str
    options: list[dict[str, str]] = Field(default_factory=list)
    free_text_allowed: bool = True


class ReadinessDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    status: ReadinessStatus = "ready"
    blocking: list[ReadinessItem] = Field(default_factory=list)
    deferred: list[ReadinessItem] = Field(default_factory=list)
    warnings: list[ReadinessItem] = Field(default_factory=list)
    resolution_questions: list[ResolutionQuestion] = Field(default_factory=list)


class ResourceContractSet(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    resources: list[dict[str, Any]] = Field(default_factory=list)
    external_config_keys: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class ImplementationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    runtime_type: Literal["langgraph_react"] = "langgraph_react"
    tool_contract_refs: list[str] = Field(default_factory=list)
    resource_contract_refs: list[str] = Field(default_factory=list)
    harness_focus: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ProductionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    status: str
    generated: list[str] = Field(default_factory=list)
    satisfied_conditions: list[str] = Field(default_factory=list)
    pending_configuration_keys: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
