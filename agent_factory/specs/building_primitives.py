from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_factory.specs.base import BaseSpec, JsonSchema, RiskLevel


class FewShotExample(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    user: str
    assistant: str
    notes: str | None = None


class InstructionSpec(BaseSpec):
    kind: Literal["InstructionSpec"] = "InstructionSpec"

    persona: str
    goal: str
    style: str | None = None
    boundaries: list[str] = Field(default_factory=list)
    principles: list[str] = Field(default_factory=list)
    few_shots: list[FewShotExample] = Field(default_factory=list)

    @field_validator("persona", "goal")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class OutputValidationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    strict: bool = True
    max_repair_attempts: int = Field(default=1, ge=0)


class OutputRepairPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    enabled: bool = True
    strategy: Literal["none", "prompt_repair", "validator_feedback"] = "validator_feedback"


class OutputSpec(BaseSpec):
    kind: Literal["OutputSpec"] = "OutputSpec"

    output_mode: Literal["text", "json_object", "json_array", "pydantic_model"] = "text"
    schema_: JsonSchema | None = Field(default=None, alias="schema")
    model_name: str | None = None
    validation: OutputValidationPolicy = Field(default_factory=OutputValidationPolicy)
    repair: OutputRepairPolicy = Field(default_factory=OutputRepairPolicy)

    @model_validator(mode="after")
    def _validate_schema(self) -> "OutputSpec":
        if self.output_mode == "text":
            return self
        if not self.schema_:
            raise ValueError("schema is required for structured output")
        schema_type = self.schema_.get("type")
        if self.output_mode in {"json_object", "pydantic_model"} and schema_type != "object":
            raise ValueError("json_object and pydantic_model outputs require object schema")
        if self.output_mode == "json_array" and schema_type != "array":
            raise ValueError("json_array output requires array schema")
        if self.output_mode == "pydantic_model" and not self.model_name:
            raise ValueError("pydantic_model output requires model_name")
        return self


class ConversationSpec(BaseSpec):
    kind: Literal["ConversationSpec"] = "ConversationSpec"

    history_window: int = Field(default=12, gt=0)
    summarize_after: int = Field(default=20, gt=0)
    summary_strategy: Literal["none", "rolling", "semantic"] = "rolling"
    retain_system_messages: bool = True
    retain_tool_messages: bool = True
    redact_before_storage: bool = True


class RunContextAccessPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    model: bool = True
    tools: bool = True
    mcp: bool = True
    context: bool = True
    memory: bool = True
    registry: bool = False


class RunContextSpec(BaseSpec):
    kind: Literal["RunContextSpec"] = "RunContextSpec"

    namespace_template: str = "agent:{agent_name}:version:{version}:instance:{instance_id}"
    dependency_refs: list[str] = Field(default_factory=list)
    access_policy: RunContextAccessPolicy = Field(default_factory=RunContextAccessPolicy)
    trace_required: bool = True
    session_required: bool = True


class Toolset(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: str
    description: str | None = None
    exposed_tools: list[str] = Field(default_factory=list)
    hidden_tools: list[str] = Field(default_factory=list)
    proposal_only: bool = True
    selection_strategy: Literal["auto", "required", "manual", "none"] = "auto"

    @model_validator(mode="after")
    def _validate_exposure(self) -> "Toolset":
        overlap = set(self.exposed_tools).intersection(self.hidden_tools)
        if overlap:
            joined = ", ".join(sorted(overlap))
            raise ValueError(f"tools cannot be both exposed and hidden: {joined}")
        return self


class ToolsetSpec(BaseSpec):
    kind: Literal["ToolsetSpec"] = "ToolsetSpec"

    toolsets: list[Toolset] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_unique_ids(self) -> "ToolsetSpec":
        _ensure_unique([toolset.id for toolset in self.toolsets], "toolset id")
        return self


class KnowledgeSource(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: str
    type: Literal["file", "directory", "url", "mcp", "vector_store", "none"]
    ref: str | None = None
    visible_to_model: bool = True
    citation_required: bool = False


class RetrieverSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: str
    source_refs: list[str] = Field(default_factory=list)
    strategy: Literal["keyword", "semantic", "hybrid", "none"] = "hybrid"
    top_k: int = Field(default=5, gt=0)


class KnowledgeSpec(BaseSpec):
    kind: Literal["KnowledgeSpec"] = "KnowledgeSpec"

    sources: list[KnowledgeSource] = Field(default_factory=list)
    retrievers: list[RetrieverSpec] = Field(default_factory=list)
    default_retriever: str | None = None
    inject_as: Literal["context", "tool", "mcp", "none"] = "context"

    @model_validator(mode="after")
    def _validate_refs(self) -> "KnowledgeSpec":
        source_ids = [source.id for source in self.sources]
        retriever_ids = [retriever.id for retriever in self.retrievers]
        _ensure_unique(source_ids, "knowledge source id")
        _ensure_unique(retriever_ids, "retriever id")
        if self.default_retriever and self.default_retriever not in retriever_ids:
            raise ValueError("default_retriever must reference an existing retriever")
        source_set = set(source_ids)
        for retriever in self.retrievers:
            missing = set(retriever.source_refs).difference(source_set)
            if missing:
                joined = ", ".join(sorted(missing))
                raise ValueError(f"retriever references missing knowledge sources: {joined}")
        return self


GuardrailStage = Literal["input", "model_request", "model_response", "tool", "output"]
GuardrailAction = Literal["block", "warn", "human_confirm", "redact", "handoff", "retry"]


class GuardrailRule(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: str
    stage: GuardrailStage
    action: GuardrailAction
    risk_level: RiskLevel = RiskLevel.MEDIUM
    description: str | None = None
    condition: str | None = None


class GuardrailSpec(BaseSpec):
    kind: Literal["GuardrailSpec"] = "GuardrailSpec"

    rules: list[GuardrailRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_unique_ids(self) -> "GuardrailSpec":
        _ensure_unique([rule.id for rule in self.rules], "guardrail rule id")
        return self


class HandoffContextPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    include_summary: bool = True
    include_trace_refs: bool = True
    include_sensitive_context: bool = False


class HandoffTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: str
    type: Literal["human", "agent", "workflow", "service"]
    target_ref: str
    condition: str | None = None
    context_policy: HandoffContextPolicy = Field(default_factory=HandoffContextPolicy)


class HandoffSpec(BaseSpec):
    kind: Literal["HandoffSpec"] = "HandoffSpec"

    targets: list[HandoffTarget] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_unique_ids(self) -> "HandoffSpec":
        _ensure_unique([target.id for target in self.targets], "handoff target id")
        return self


TraceSpanType = Literal[
    "agent_run",
    "model_generation",
    "prompt_render",
    "tool_proposal",
    "tool_call",
    "mcp_call",
    "context_load",
    "guardrail_check",
    "handoff",
    "checkpoint",
]


class TraceSpanConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    type: TraceSpanType
    enabled: bool = True


class ObservabilitySpec(BaseSpec):
    kind: Literal["ObservabilitySpec"] = "ObservabilitySpec"

    trace_enabled: bool = True
    spans: list[TraceSpanConfig] = Field(default_factory=list)
    record_usage: bool = True
    record_prompt_hash: bool = True
    record_response_hash: bool = True
    record_content: bool = False
    forbidden_fields: list[str] = Field(
        default_factory=lambda: [
            "api_key",
            "secret",
            "authorization",
            "auth_header",
            "tool_auth_token",
        ]
    )
    allowed_sensitive_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_sensitive_fields(self) -> "ObservabilitySpec":
        sensitive = {"api_key", "secret", "authorization", "auth_header", "tool_auth_token"}
        allowed = {field.lower() for field in self.allowed_sensitive_fields}
        forbidden = {field.lower() for field in self.forbidden_fields}
        unsafe_allowed = allowed.intersection(sensitive)
        if unsafe_allowed:
            joined = ", ".join(sorted(unsafe_allowed))
            raise ValueError(f"sensitive fields cannot be explicitly allowed: {joined}")
        missing_forbidden = sensitive.difference(forbidden)
        if missing_forbidden:
            joined = ", ".join(sorted(missing_forbidden))
            raise ValueError(f"sensitive fields must remain forbidden: {joined}")
        _ensure_unique([span.type for span in self.spans], "trace span type")
        return self


class AgentPackagePrimitives(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    instructions: InstructionSpec
    output: OutputSpec
    conversation: ConversationSpec
    run_context: RunContextSpec
    toolsets: ToolsetSpec
    knowledge: KnowledgeSpec
    guardrails: GuardrailSpec
    handoffs: HandoffSpec
    observability: ObservabilitySpec


def _ensure_unique(values: list[str], label: str) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        joined = ", ".join(sorted(duplicates))
        raise ValueError(f"duplicate {label}: {joined}")

