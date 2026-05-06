from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ServiceKind = Literal[
    "model_service",
    "tool_registry",
    "memory_engine",
    "knowledge_engine",
    "context_engine",
    "policy_engine",
    "observability_manager",
    "checkpoint_manager",
    "harness_bridge",
]

HookPoint = Literal[
    "pre_cognitive",
    "post_cognitive",
    "pre_operational",
    "post_operational",
    "pre_governance",
    "post_governance",
    "pre_terminal",
    "post_terminal",
    "on_interrupt",
    "on_resume",
]

BindingType = Literal[
    "prompt",
    "tool_access",
    "policy_profile",
    "retrieval_profile",
    "strategy_profile",
    "output_formatter",
    "custom",
]


class ServiceBindingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_id: str
    kind: ServiceKind
    required: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class NodeBindingTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    impl: str


class PromptBindingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_id: str
    template: str
    variables: list[str] = Field(default_factory=list)


class ToolAccessBindingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_tool_ids: list[str] = Field(default_factory=list)
    approval_policy: str = "standard"


class PolicyProfileBindingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    rules: dict[str, Any] = Field(default_factory=dict)


class RetrievalProfileBindingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_source: str = "current_user_input"
    top_k: int = 5


class OutputFormatterBindingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    formatter_id: str
    mode: str = "identity"
    config: dict[str, Any] = Field(default_factory=dict)


class NodeBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    binding_id: str
    binding_type: BindingType
    target: NodeBindingTarget
    payload: dict[str, Any] = Field(default_factory=dict)


class HookBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    binding_id: str
    hook_point: HookPoint
    enabled: bool = True
    order: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)


class BindingSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    services: list[ServiceBindingSpec] = Field(default_factory=list)
    node_bindings: list[NodeBinding] = Field(default_factory=list)
    hooks: list[HookBinding] = Field(default_factory=list)
