from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_factory.specs.base import BaseSpec, JsonSchema, Metadata, RiskLevel
from agent_factory.specs.building_primitives import AgentPackagePrimitives


ReleaseStatus = Literal["draft", "candidate", "available", "deprecated", "failed"]
RuntimeKind = Literal["workflow", "graph"]


class PackageManifest(BaseSpec):
    kind: Literal["PackageManifest"] = "PackageManifest"

    agent_id: str
    agent_name: str
    version: str = "1.0.0"
    status: ReleaseStatus = "draft"
    description: str | None = None
    entrypoint: str = "agent_factory.agent.worker"
    package_format: str = "agentpackage.v1"
    tags: list[str] = Field(default_factory=list)


class RuntimeStep(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: str
    type: Literal[
        "load_context",
        "load_memory",
        "model_turn",
        "route_tools",
        "execute_tool",
        "mcp_call",
        "write_memory",
        "write_trace",
        "handoff",
    ]
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class RuntimeSpec(BaseSpec):
    kind: Literal["RuntimeSpec"] = "RuntimeSpec"

    runtime_type: RuntimeKind = "workflow"
    workflow_steps: list[RuntimeStep] = Field(
        default_factory=lambda: [
            RuntimeStep(id="load_context", type="load_context"),
            RuntimeStep(id="load_memory", type="load_memory"),
            RuntimeStep(id="model_turn", type="model_turn"),
            RuntimeStep(id="route_tools", type="route_tools"),
            RuntimeStep(id="write_memory", type="write_memory"),
            RuntimeStep(id="write_trace", type="write_trace"),
        ]
    )
    graph: dict[str, Any] = Field(default_factory=dict)
    max_turns: int = Field(default=6, gt=0)
    timeout_seconds: int = Field(default=60, gt=0)


class ToolImplementationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    language: Literal["python"] = "python"
    path: str
    entrypoint: str = "run"


class ToolApprovalSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    required: bool = True
    reason: str | None = None


class GeneratedToolDraftSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    schema_version: str = "0.1"
    kind: Literal["GeneratedToolDraft"] = "GeneratedToolDraft"
    metadata: Metadata
    tool_id: str
    toolset_id: str | None = None
    source: Literal["factory_generated", "hand_written"] = "factory_generated"
    status: ReleaseStatus = "draft"
    risk_level: RiskLevel = RiskLevel.MEDIUM
    exposure: Literal["exposed", "hidden"] = "exposed"
    proposal_only: bool = True
    selection_strategy: Literal["auto", "required", "manual", "none"] = "auto"
    implementation: ToolImplementationSpec
    input_schema: JsonSchema = Field(default_factory=lambda: {"type": "object"})
    output_schema: JsonSchema = Field(default_factory=lambda: {"type": "object"})
    approval: ToolApprovalSpec = Field(default_factory=ToolApprovalSpec)

    @model_validator(mode="after")
    def _validate_status(self) -> "GeneratedToolDraftSpec":
        if self.status == "available" and self.approval.required:
            raise ValueError("approved tools must clear approval.required before becoming available")
        return self


class ToolsSpec(BaseSpec):
    kind: Literal["ToolsSpec"] = "ToolsSpec"

    generated_tools: list[str] = Field(default_factory=list)
    default_policy: Literal["proposal_only", "safe_execute", "human_confirm"] = "proposal_only"
    allow_draft_execution: bool = False
    require_approval_for_generated_code: bool = True


class MCPServerSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: str
    source_ref: str | None = None
    transport: Literal["stdio"] = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    enabled: bool = False
    health_check: dict[str, Any] = Field(default_factory=lambda: {"enabled": True})


class MCPBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: str
    source_id: str
    capability_ref: str
    risk_level: RiskLevel = RiskLevel.MEDIUM
    visible_to_model: bool = True
    proposal_only: bool = True
    input_mapping: dict[str, Any] = Field(default_factory=dict)
    output_mapping: dict[str, Any] = Field(default_factory=dict)


class MCPBindingSpec(BaseSpec):
    kind: Literal["MCPBindingSpec"] = "MCPBindingSpec"

    servers: list[MCPServerSpec] = Field(default_factory=list)
    bindings: list[MCPBinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_refs(self) -> "MCPBindingSpec":
        for binding in self.bindings:
            if not binding.capability_ref.startswith("mcp.") or "@" not in binding.capability_ref:
                raise ValueError("mcp capability_ref must look like mcp.<name>@<version>")
        return self


class ContextSourceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: str
    type: Literal["static", "fixture", "memory", "mcp"]
    content: str | None = None
    ref: str | None = None
    visible_to_model: bool = True
    visible_to_tools: bool = True
    hidden_from_model: list[str] = Field(default_factory=list)


class ContextSpec(BaseSpec):
    kind: Literal["ContextSpec"] = "ContextSpec"

    sources: list[ContextSourceSpec] = Field(default_factory=list)
    max_visible_items: int = Field(default=8, gt=0)
    redact_fields: list[str] = Field(
        default_factory=lambda: [
            "api_key",
            "secret",
            "authorization",
            "auth_header",
            "tool_auth_token",
        ]
    )


class MemorySpec(BaseSpec):
    kind: Literal["MemorySpec"] = "MemorySpec"

    backend: Literal["filesystem"] = "filesystem"
    session_memory_file: str = "memory/session_memory.jsonl"
    summary_memory_file: str = "memory/summary_memory.jsonl"
    enabled: bool = True
    namespace_template: str = "agent:{agent_id}:session:{session_id}"
    redact_before_storage: bool = True


class HarnessPackageScenario(BaseModel):
    model_config = ConfigDict(extra="allow", validate_assignment=True)

    id: str
    turns: list[dict[str, Any]]
    expected: dict[str, Any] = Field(default_factory=dict)
    observe: dict[str, Any] = Field(default_factory=dict)


class HarnessPackageSpec(BaseSpec):
    kind: Literal["HarnessSpec"] = "HarnessSpec"

    observation: dict[str, Any] = Field(default_factory=dict)
    fixtures: dict[str, Any] = Field(default_factory=dict)
    scenarios: list[HarnessPackageScenario]


class FullAgentPackage(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    primitives: AgentPackagePrimitives
    manifest: PackageManifest
    runtime: RuntimeSpec
    tools: ToolsSpec
    mcp: MCPBindingSpec
    context: ContextSpec
    memory: MemorySpec
    harness: HarnessPackageSpec
    generated_tools: list[GeneratedToolDraftSpec] = Field(default_factory=list)


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
